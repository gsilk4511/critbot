# Private involvement questionnaire.
import json
import csv
import io
import math
import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, request, render_template, redirect, url_for, flash, abort, g, Response

# key, label, kind, choices (check options for multiple)
QUESTIONS=(
 ('preferred_name','What should guildmates call you?','text',()),
 ('main_name','What is your main character’s name?','text',()),
 ('playstyle','What do you enjoy in WoW?','multi',('Dungeons','Raiding','Leveling','PvP','Gold farming','Professions','Guild events','Socializing','Solo play')),
 ('frequency','How often do you play?','single',('Daily','Several times weekly','Weekly','Occasionally','Varies')),
 ('availability','When are you usually available?','multi',('Weekday mornings','Weekday afternoons','Weekday evenings','Weekend mornings','Weekend afternoons','Weekend evenings','Schedule varies')),
 ('activities','Which guild events would you join?','multi',('Dungeons','Raids','PvP nights','Guild races','Contests','Movie nights','Social hangouts','Leveling parties')),
 ('helping','Would you like to help organize things?','single',('Yes','Maybe, depending on time','No, I prefer participating')),
 ('strengths','Where would you be interested in helping?','multi',('Welcoming members','Running events','Dungeon groups','Raid organization','Helping new players','Discord/technology','Not interested right now')),
 ('expectations','What do you want most from Flick the Crit?','multi',('Friends and community','People to run content with','Learning the game','Casual atmosphere','Progression','Events','A place to relax')),
 ('feedback','What would make the guild better for you? (optional)','textarea',()),
)
STATUSES=('new','in_review','follow_up','completed')

def safe_answers(raw):
    """Old or damaged response rows must never crash either questionnaire page."""
    try:
        val=json.loads(raw or '{}')
    except (ValueError,TypeError):
        return {}
    return val if isinstance(val,dict) else {}

def timestamp_order(value):
    """SQLite timestamps and ISO 8601 timestamps have different representations.

    In 1.2.5 sorting tried int('2026...T...+00:00') and raised ValueError.
    Always convert to a comparable timestamp instead.
    """
    try:
        if not value: return 0.0
        val=str(value).strip().replace('Z','+00:00')
        dt=datetime.fromisoformat(val)
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError,TypeError,OverflowError):
        return 0.0

def init_involvement(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS guild_involvement (
      member_id TEXT PRIMARY KEY, answers_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'new',
      assigned_to TEXT NOT NULL DEFAULT '',officer_note TEXT NOT NULL DEFAULT '',
      submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS guild_involvement_history(
      id INTEGER PRIMARY KEY AUTOINCREMENT,member_id TEXT NOT NULL,actor_id TEXT NOT NULL,
      action TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    ''')
    # Older installs have a response table but lack the officer-review fields.
    # Check again inside the write transaction in case two requests upgrade at once.
    fields = (
        ('status', "TEXT NOT NULL DEFAULT 'new'"),
        ('assigned_to', "TEXT NOT NULL DEFAULT ''"),
        ('officer_note', "TEXT NOT NULL DEFAULT ''"),
    )
    columns = {row[1] for row in db.execute('PRAGMA table_info(guild_involvement)')}
    if any(name not in columns for name, _ in fields):
        db.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in db.execute('PRAGMA table_info(guild_involvement)')}
        for name, declaration in fields:
            if name not in columns:
                db.execute(f'ALTER TABLE guild_involvement ADD COLUMN {name} {declaration}')

def blueprint(connect):
    bp=Blueprint('involvement',__name__)
    @bp.get('/guild/involvement')
    def form():
        uid=str(g.dashboard_access['discord_id'])
        with connect() as db:
            # Harmless, idempotent startup recovery for an out-of-order code-only deploy.
            init_involvement(db)
            row=db.execute('SELECT answers_json,submitted_at FROM guild_involvement WHERE member_id=?',(uid,)).fetchone()
            has_characters=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='member_characters'").fetchone()
            cols={c[1] for c in db.execute('PRAGMA table_info(member_characters)')} if has_characters else set()
            char=(db.execute('SELECT name FROM member_characters WHERE member_id=? AND is_main=1',(uid,)).fetchone()
                  if {'name','member_id','is_main'}<=cols else None)
        values=safe_answers(row['answers_json']) if row else {}
        if not values.get('main_name') and char:values['main_name']=char['name']
        return render_template('involvement_form.html',questions=QUESTIONS,values=values,submitted_at=row['submitted_at'] if row else '')
    @bp.post('/guild/involvement')
    def submit():
        uid=str(g.dashboard_access['discord_id']);answers={}
        for key,_,kind,choices in QUESTIONS:
            if kind=='multi':
                value=request.form.getlist(key)
                if len(value)!=len(set(value)) or any(v not in choices for v in value) or len(value)>len(choices):abort(400)
                answers[key]=value
            else:
                value=request.form.get(key,'').strip()
                if len(value)>(700 if kind=='textarea' else 80):abort(400)
                if kind=='single' and value not in choices:abort(400)
                if kind!='textarea' and not value:abort(400)
                answers[key]=value
        with connect() as db:
            init_involvement(db)
            db.execute('''INSERT INTO guild_involvement(member_id,answers_json,status) VALUES(?,?,'new')
             ON CONFLICT(member_id) DO UPDATE SET answers_json=excluded.answers_json,status='new',
             assigned_to='',officer_note='',submitted_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP''',(uid,json.dumps(answers)))
            db.execute("INSERT INTO guild_involvement_history(member_id,actor_id,action) VALUES(?,?,'member_submitted')",(uid,uid))
        flash('Your private answers have been saved.','success');return redirect(url_for('involvement.form'))
    def load_review_data():
        # A small officer queue: filter/sort in memory so the current SQLite schema
        # is preserved and old saved questionnaires need no migration.
        with connect() as db:
            init_involvement(db)
            people=[dict(row) for row in db.execute('''SELECT v.*,COALESCE(m.display_name,v.member_id) display_name
                FROM guild_involvement v LEFT JOIN member_directory m ON m.member_id=v.member_id''')]
            reviewers=[dict(r) for r in db.execute('SELECT discord_id,display_name FROM dashboard_access ORDER BY display_name COLLATE NOCASE')]
        for person in people:
            person['answers']=safe_answers(person.get('answers_json'))
        counts={key:sum(person['status']==key for person in people) for key in STATUSES}
        opts={
            'q':request.args.get('q','').strip()[:100],
            'status':request.args.get('status','all'),
            'reviewer':request.args.get('reviewer','all'),
            'activity':request.args.get('activity','all'),
            'sort':request.args.get('sort','needs_attention')
        }
        if opts['status'] not in (*STATUSES,'all'):opts['status']='all'
        if opts['sort'] not in ('needs_attention','newest','oldest','name','updated'):opts['sort']='needs_attention'
        if opts['reviewer'] not in ('all','unassigned','mine') and not any(r['discord_id']==opts['reviewer'] for r in reviewers):opts['reviewer']='all'
        activities=sorted({val for p in people for field in ('playstyle','activities','strengths','expectations')
                           for val in (p['answers'].get(field,[]) if isinstance(p['answers'].get(field),list) else [])
                           if isinstance(val,str)})
        if opts['activity']!='all' and opts['activity'] not in activities:opts['activity']='all'
        status_rank={'new':0,'follow_up':1,'in_review':2,'completed':3}
        filtered=[]
        q=opts['q'].casefold()
        for p in people:
            if opts['status']!='all' and p['status']!=opts['status']:continue
            if opts['reviewer']=='unassigned' and p['assigned_to']:continue
            if opts['reviewer']=='mine' and p['assigned_to']!=str(g.dashboard_access['discord_id']):continue
            if opts['reviewer'] not in ('all','unassigned','mine') and p['assigned_to']!=opts['reviewer']:continue
            if opts['activity']!='all' and not any(opts['activity'] in (p['answers'].get(k) or []) for k in ('playstyle','activities','strengths','expectations')):continue
            if q and q not in ' '.join(str(x) for x in (p['display_name'],p['member_id'],p['answers'].get('preferred_name',''),p['answers'].get('main_name',''))).casefold():continue
            filtered.append(p)
        if opts['sort']=='name':filtered.sort(key=lambda p:(str(p['answers'].get('preferred_name') or p['display_name']).casefold(),p['member_id']))
        elif opts['sort']=='oldest':filtered.sort(key=lambda p:(timestamp_order(p.get('submitted_at')),p['member_id']))
        elif opts['sort']=='newest':filtered.sort(key=lambda p:(timestamp_order(p.get('submitted_at')),p['member_id']),reverse=True)
        elif opts['sort']=='updated':filtered.sort(key=lambda p:(timestamp_order(p.get('updated_at')),p['member_id']),reverse=True)
        else:filtered.sort(key=lambda p:(status_rank.get(p['status'],9),-timestamp_order(p.get('updated_at')),str(p.get('member_id',''))))
        return people,filtered,reviewers,counts,activities,opts

    @bp.get('/officer/involvement')
    def review():
        all_people,filtered,reviewers,counts,activities,opts=load_review_data()
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:page=1
        per_page=15
        total_pages=max(1,math.ceil(len(filtered)/per_page))
        page=min(page,total_pages)
        entries=filtered[(page-1)*per_page:page*per_page]
        review_names={str(r['discord_id']):r['display_name'] for r in reviewers}
        actor=g.dashboard_access
        can_handle=actor['level'] in ('owner','pope') or 'involvement_handle' in actor['permissions']
        return render_template('involvement_review.html',entries=entries,questions=QUESTIONS,reviewers=reviewers,
            reviewer_names=review_names,can_handle=can_handle,statuses=STATUSES,filters=opts,counts=counts,
            activity_options=activities,all_count=len(all_people),filtered_count=len(filtered),page=page,pages=total_pages)

    def csv_cell(value):
        if isinstance(value,list):value='; '.join(str(v) for v in value)
        value=str(value or '')
        # Prevent an attacker-controlled character/name/note from executing Excel formulas.
        if value.lstrip().startswith(('=','+','-','@')) or value[:1] in ('\t','\r','\n'):
            return "'"+value
        return value

    @bp.get('/officer/involvement/export.csv')
    def export_csv():
        _,filtered,reviewers,_,_,_=load_review_data()
        names={str(r['discord_id']):r['display_name'] for r in reviewers}
        stream=io.StringIO(newline='')
        writer=csv.writer(stream)
        writer.writerow(['Discord ID','Discord display name','Preferred name','Main character','Status','Assigned reviewer',
            'Submitted','Last updated']+[label for _,label,_,_ in QUESTIONS]+['Private officer notes'])
        for p in filtered:
            a=p['answers']
            writer.writerow([csv_cell(v) for v in (
                p['member_id'],p['display_name'],a.get('preferred_name',''),a.get('main_name',''),p['status'],
                names.get(p['assigned_to'],'Unassigned' if not p['assigned_to'] else p['assigned_to']),
                p['submitted_at'],p['updated_at'],*[a.get(key,'') for key,_,_,_ in QUESTIONS],p['officer_note'])])
        response=Response('\ufeff'+stream.getvalue(),mimetype='text/csv; charset=utf-8')
        response.headers['Content-Disposition']='attachment; filename="critbot-involvement-responses.csv"'
        response.headers['Cache-Control']='private, no-store'
        return response

    @bp.post('/officer/involvement/<member_id>/handle')
    def handle(member_id):
        if not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:abort(400)
        status=request.form.get('status','');assigned=request.form.get('assigned_to','').strip();note=request.form.get('officer_note','').strip()
        if status not in STATUSES or len(note)>1500:abort(400)
        with connect() as db:
            init_involvement(db)
            if assigned and not db.execute('SELECT 1 FROM dashboard_access WHERE discord_id=?',(assigned,)).fetchone() and assigned!=g.dashboard_access['discord_id']:abort(400)
            if not db.execute('SELECT 1 FROM guild_involvement WHERE member_id=?',(member_id,)).fetchone():abort(404)
            db.execute('UPDATE guild_involvement SET status=?,assigned_to=?,officer_note=?,updated_at=CURRENT_TIMESTAMP WHERE member_id=?',(status,assigned,note,member_id))
            db.execute("INSERT INTO guild_involvement_history(member_id,actor_id,action,note) VALUES(?,?,'reviewed',?)",(member_id,g.dashboard_access['discord_id'],note[:500]))
        flash('Private review updated.','success')
        opts={}
        for name in ('q','status','reviewer','activity','sort','page'):
            value=request.form.get('return_'+name,'').strip()
            if value and len(value)<=100:opts[name]=value
        return redirect(url_for('involvement.review',**opts)+'#response-'+member_id)
    return bp

