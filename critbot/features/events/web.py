import json, calendar
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint,render_template,request,redirect,url_for,flash,abort,g
from .store import parse_event,describe,participants,parse_config,DEFAULT_SLOTS,CLASSES
from ...channel_overrides import selected_channel

def blueprint(connect):
    bp=Blueprint('events',__name__)
    @bp.get('/events')
    def home():
        with connect() as db:
            ability=g.dashboard_access
            public_only=not (ability['level'] in ('owner','pope') or 'events_manage' in ability['permissions'])
            query="SELECT * FROM guild_events" + (" WHERE status IN ('posted','full','started','completed')" if public_only else "") + " ORDER BY CASE WHEN status IN ('completed','cancelled') THEN 1 ELSE 0 END, starts_at,id"
            events=[describe(e) for e in db.execute(query)]
        scheduled=[e for e in events if e['kind']!='dungeon' and e['status'] not in ('cancelled','completed')]
        history=[e for e in events if e['kind']!='dungeon' and e['status'] in ('cancelled','completed')]
        dungeons=[e for e in events if e['kind']=='dungeon' and e['status'] in ('queued','posting','posted','full','started')]
        # Calendar is a view over scheduled event records; dungeons have no date.
        raw=request.args.get('month','')
        try:
            y,m=map(int,raw.split('-'))
            if not (2020<=y<=2100 and 1<=m<=12):raise ValueError()
            today=date(y,m,1)
        except (ValueError,TypeError):today=date.today().replace(day=1)
        cal=calendar.Calendar(firstweekday=6).monthdatescalendar(today.year,today.month)
        by_day={}
        for e in events:
            if e['kind']=='dungeon':continue
            # input_time is already converted to US/Eastern in describe().
            day=e['input_time'][:10]
            by_day.setdefault(day,[]).append(e)
        prev=(today.replace(day=1).toordinal()-1)
        prevdate=date.fromordinal(prev).replace(day=1)
        nextdate=date(today.year+1,1,1) if today.month==12 else date(today.year,today.month+1,1)
        ability=g.dashboard_access
        can=lambda name:ability['level'] in ('owner','pope') or name in ability['permissions']
        return render_template('events.html',events=scheduled,history=history,dungeons=dungeons,weeks=cal,by_day=by_day,
            month=today.strftime('%B %Y'),month_key=today.strftime('%Y-%m'),
            prev_month=prevdate.strftime('%Y-%m'),next_month=nextdate.strftime('%Y-%m'),
            can_create=can('events_create'),can_manage=can('events_manage'),can_delete=can('events_delete'))
    @bp.route('/events/new',methods=['GET','POST'])
    @bp.route('/events/<int:event_id>/edit',methods=['GET','POST'])
    def editor(event_id=None):
        ability=g.dashboard_access
        if ability['level'] not in ('owner','pope') and 'events_create' not in ability['permissions']:abort(403)
        with connect() as db:
            item=db.execute('SELECT * FROM guild_events WHERE id=?',(event_id,)).fetchone() if event_id else None
            members=db.execute('SELECT member_id,display_name FROM member_directory WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE').fetchall()
            channels=db.execute('SELECT * FROM auto_channel_directory ORDER BY name').fetchall()
        if event_id and item is None:abort(404)
        if (item and item['kind']=='dungeon') or (not item and request.values.get('kind')=='dungeon'):
            flash('Dungeon recruitment is a live Discord post, not a scheduled event. Use /dungeon in your Discord channel.','error')
            return redirect(url_for('events.detail',event_id=event_id) if item else url_for('events.home'))
        if item and item['status'] not in ('draft','failed','posted'):
            flash('This event cannot be edited while posting or after closing.','error');return redirect(url_for('events.detail',event_id=event_id))
        if request.method=='POST':
            try:
                event_form=request.form.to_dict()
                if item:event_form['kind']=item['kind']
                values=parse_event(event_form)
                if not item and event_form.get('kind')!='dungeon':
                    if datetime.fromisoformat(values[2]) <= datetime.now(timezone.utc)+timedelta(minutes=2):
                        raise ValueError('Choose a future start time. Discord cannot create Scheduled Events in the past.')
                if item and item['message_id']:kind,config=item['kind'],item['config_json']
                else:kind,config=parse_config(request.form)
                channel=(item['channel_id'] if item and item['message_id'] else selected_channel(request.form, 'channel_id'))
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    current=db.execute('SELECT * FROM guild_events WHERE id=?',(event_id,)).fetchone() if event_id else None
                    if current and current['status'] not in ('draft','failed','posted'):raise ValueError('The event status changed. Refresh before editing.')
                    if current and current['message_id']:
                        channel=current['channel_id'];kind=current['kind'];config=current['config_json']
                    # IDs may be supplied manually while the Discord directory is stale.
                    # Discord publisher checks real access and surfaces any failure.
                    if current and not current['message_id'] and json.loads(current['config_json']).get('leader_id'):
                        if kind!='dungeon':raise ValueError('Keep this listing as Dungeon LFG, or create a separate event.')
                        cfg=json.loads(config);old=json.loads(current['config_json'])
                        owner=db.execute('SELECT choice,class_name FROM guild_event_members WHERE event_id=? AND member_id=?',(event_id,old['leader_id'])).fetchone()
                        if not owner or owner['choice'] not in [o['key'] for o in cfg['slots']] or owner['class_name'] not in cfg['classes']:raise ValueError('Keep the leader’s signup option and class available.')
                        cfg.update(leader_id=old['leader_id'],leader_name=old['leader_name']);config=json.dumps(cfg)
                    leader=None
                    if kind=='dungeon' and not current:
                        leader_id=request.form.get('leader_id','')
                        leader=db.execute('SELECT member_id,display_name FROM member_directory WHERE member_id=? AND is_bot=0',(leader_id,)).fetchone()
                        cfg=json.loads(config);slot=request.form.get('leader_slot','');cls=request.form.get('leader_class','')
                        if leader is None:raise ValueError('Choose the member starting this dungeon group.')
                        if slot not in [o['key'] for o in cfg['slots']] or cls not in cfg['classes']:raise ValueError('Choose the leader’s role and class.')
                        cfg['leader_id']=leader['member_id'];cfg['leader_name']=leader['display_name'];config=json.dumps(cfg)
                    if current:
                        db.execute('UPDATE guild_events SET title=?,description=?,starts_at=?,location=?,channel_id=?,kind=?,config_json=?,revision=revision+1 WHERE id=?',values+(channel,kind,config,event_id))
                    else:
                        event_id=db.execute('INSERT INTO guild_events(title,description,starts_at,location,channel_id,kind,config_json) VALUES(?,?,?,?,?,?,?)',values+(channel,kind,config)).lastrowid
                        if leader:db.execute("INSERT INTO guild_event_members(event_id,member_id,name,rsvp,choice,class_name) VALUES(?,?,?,'going',?,?)",(event_id,leader['member_id'],leader['display_name'],slot,cls))
                flash('Event saved. Published messages update in a few seconds.','success');return redirect(url_for('events.detail',event_id=event_id))
            except ValueError as error:flash(str(error),'error')
        kind=request.form.get('kind',item['kind'] if item else request.args.get('kind','general'))
        if kind not in DEFAULT_SLOTS:kind='general'
        data=describe(item) if item else None
        slots='\n'.join(o['name']+' | '+str(o['capacity']) for o in data['config'].get('slots',[])) if data else DEFAULT_SLOTS[kind]
        return render_template('event_form.html',item=data,channels=channels,members=members,kind=kind,slots=slots,classes=', '.join(data['config'].get('classes',[])) if data and data['kind']!='general' else CLASSES,defaults=DEFAULT_SLOTS,proposed_date=request.args.get('date',''))
    @bp.get('/events/<int:event_id>')
    def detail(event_id):
        with connect() as db:
            event=db.execute('SELECT * FROM guild_events WHERE id=?',(event_id,)).fetchone()
            if event is None:abort(404)
            access=g.dashboard_access
            if event['status'] not in ('posted','full','started','completed') and access['level'] not in ('owner','pope') and 'events_manage' not in access['permissions']:abort(404)
            members=db.execute('SELECT member_id,display_name FROM member_directory WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE').fetchall()
            people=participants(db,event_id)
        access=g.dashboard_access
        can=lambda name:access['level'] in ('owner','pope') or name in access['permissions']
        return render_template('event_detail.html',event=describe(event),people=people,members=members,can_manage=can('events_manage'),can_delete=can('events_delete'))
    @bp.post('/events/<int:event_id>/action')
    def action(event_id):
        operation=request.form.get('operation')
        with connect() as db:
            db.execute('BEGIN IMMEDIATE');event=db.execute('SELECT * FROM guild_events WHERE id=?',(event_id,)).fetchone()
            if event is None:abort(404)
            status=event['status']
            if operation=='delete' and status not in ('posting','deleting'):
                if event['message_id']:
                    db.execute("UPDATE guild_events SET status='deleting',last_error='' WHERE id=?",(event_id,))
                else:
                    db.execute('DELETE FROM guild_event_members WHERE event_id=?',(event_id,))
                    db.execute('DELETE FROM guild_events WHERE id=?',(event_id,))
                    flash('Event deleted.','success');return redirect(url_for('events.home'))
            elif operation=='publish' and status in ('draft','failed','uncertain') and not event['message_id']:
                db.execute("UPDATE guild_events SET status='queued',last_error='' WHERE id=?",(event_id,))
            elif operation in ('full','start','reopen') and event['kind']=='dungeon' and status in ('posted','full'):
                db.execute('UPDATE guild_events SET status=?,revision=revision+1 WHERE id=?',({'full':'full','start':'started','reopen':'posted'}[operation],event_id))
            elif operation=='retry-update' and event['message_id'] and status in ('posted','cancelled','completed','full','started','expired'):
                db.execute('UPDATE guild_events SET revision=revision+1 WHERE id=?',(event_id,))
            elif operation=='retry-schedule' and event['kind']!='dungeon' and event['message_id'] and status in ('posted','cancelled'):
                db.execute("UPDATE guild_events SET scheduled_retry_at='',scheduled_error='',scheduled_synced_revision=0 WHERE id=?",(event_id,))
            elif operation in ('cancel','complete') and status in ('draft','failed','posted','full','started','expired'):
                db.execute('UPDATE guild_events SET status=?,revision=revision+1 WHERE id=?',('cancelled' if operation=='cancel' else 'completed',event_id))
            else:
                flash('That action is unavailable for the current event status.','error');return redirect(url_for('events.detail',event_id=event_id))
        flash('Event action saved. Critbot will update Discord when online.','success');return redirect(url_for('events.detail',event_id=event_id))
    @bp.post('/events/<int:event_id>/attendance')
    def attendance(event_id):
        mid=request.form.get('member_id','');attended=request.form.get('attended')
        if not mid.isascii() or not mid.isdecimal() or len(mid)>20 or attended not in ('0','1'):abort(400)
        with connect() as db:
            event=db.execute('SELECT status FROM guild_events WHERE id=?',(event_id,)).fetchone()
            if event is None:abort(404)
            if event['status'] in ('deleting','delete_failed'):abort(409)
            existing=db.execute('SELECT name FROM guild_event_members WHERE event_id=? AND member_id=?',(event_id,mid)).fetchone()
            member=db.execute('SELECT display_name FROM member_directory WHERE member_id=? AND is_bot=0',(mid,)).fetchone()
            if not member and not existing:abort(404)
            name=member[0] if member else existing[0]
            db.execute('''INSERT INTO guild_event_members(event_id,member_id,name,attended) VALUES(?,?,?,?)
                ON CONFLICT(event_id,member_id) DO UPDATE SET attended=excluded.attended,updated_at=CURRENT_TIMESTAMP''',(event_id,mid,name,int(attended)))
        flash('Attendance saved. RSVP and attendance are tracked separately.','success');return redirect(url_for('events.detail',event_id=event_id))
    return bp
