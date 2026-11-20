"""Player-run instant groups; separate from scheduled guild events.

Dungeon groups reuse the legacy guild_events Discord publisher. Leveling and
questing have an independent dashboard roster; Discord publication for those
kinds is not implemented in this development revision.
"""
import sqlite3
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from .characters import owned, add as add_character
from .features.events.store import CLASS_ROLES, describe, make_dungeon_post
from .social import notify

KINDS = ('leveling', 'questing')

def init_groups(db):
    db.execute('''CREATE TABLE IF NOT EXISTS instant_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('leveling','questing')),
        leader_id TEXT NOT NULL, title TEXT NOT NULL, zone TEXT NOT NULL, quest_name TEXT NOT NULL DEFAULT '',
        min_level INTEGER NOT NULL, max_level INTEGER NOT NULL, capacity INTEGER NOT NULL DEFAULT 5,
        notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE IF NOT EXISTS instant_group_members (
        group_id INTEGER NOT NULL, member_id TEXT NOT NULL, character_name TEXT NOT NULL,
        class_name TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 1,
        joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(group_id,member_id))''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_instant_groups_active ON instant_groups(status,created_at)')

def find_groups(db, user):
    result=[]
    for row in db.execute("SELECT * FROM instant_groups WHERE status='open' ORDER BY id DESC LIMIT 90"):
        item=dict(row)
        people=[dict(p) for p in db.execute('SELECT * FROM instant_group_members WHERE group_id=? ORDER BY joined_at',(row['id'],))]
        item.update(count=len(people),open_count=max(0,int(row['capacity'])-len(people)),joined=any(p['member_id']==str(user) for p in people),
                    roster=people,link=url_for('groups.detail',group_id=row['id']),kind_label=row['kind'].capitalize())
        result.append(item)
    return result

def _clean(s, limit, label, required=True):
    val=str(s or '').strip()
    if (required and not val) or len(val)>limit:raise ValueError(f'{label} must be 1–{limit} characters.')
    return val

def _level(value,label):
    try: n=int(value)
    except (TypeError,ValueError):raise ValueError(f'Choose a valid {label} from 1 to 60.')
    if not 1<=n<=60:raise ValueError(f'Choose a valid {label} from 1 to 60.')
    return n

def blueprint(connect):
    bp=Blueprint('groups',__name__)

    @bp.get('/groups')
    def home():
        uid=str(g.dashboard_access['discord_id'])
        with connect() as db:
            groups=find_groups(db,uid)
            dungeons=[]
            for row in db.execute("SELECT * FROM guild_events WHERE kind='dungeon' AND status IN ('queued','posting','posted','full','started') ORDER BY id DESC LIMIT 50"):
                event=describe(row)
                people=[dict(p) for p in db.execute("SELECT * FROM guild_event_members WHERE event_id=? AND rsvp='going'",(row['id'],))]
                capacities={s['key']:s for s in event['config'].get('slots',[])}
                used={key:sum(1 for p in people if p['choice']==key) for key in capacities}
                event.update(kind_label='Dungeon',count=len(people),open_count=sum(max(0,s['capacity']-used[s['key']]) for s in capacities.values()),
                    joined=any(p['member_id']==uid for p in people),link=url_for('hub.group',event_id=row['id']))
                dungeons.append(event)
            chars=owned(db,uid)
            channels=db.execute('SELECT channel_id,name FROM auto_channel_directory ORDER BY name').fetchall()
        return render_template('groups.html',instant=groups,dungeons=dungeons,characters=chars,
                               channels=channels,classes=tuple(CLASS_ROLES))

    @bp.post('/groups/new')
    def create():
        uid=str(g.dashboard_access['discord_id'])
        kind=request.form.get('kind','')
        if kind not in ('dungeon',*KINDS):abort(400)
        try:
            char_id=request.form.get('character_id','')
            with connect() as db:
                char=next((c for c in owned(db,uid) if str(c['id'])==char_id),None)
                if not char:raise ValueError('Select one of your registered main or alt characters. Add one in My Characters first.')
                toon,cls=char['name'],char['class_name']
                if kind=='dungeon':
                    dungeon=_clean(request.form.get('dungeon'),80,'Dungeon')
                    role=_clean(request.form.get('role'),10,'Role')
                    if role not in char['roles']:raise ValueError('This character is not registered for that role. Change its roles in My Characters.')
                    notes=_clean(request.form.get('notes'),600,'Notes',False)
                    channel=request.form.get('channel_id_manual','').strip() or request.form.get('channel_id','').strip()
                    if not channel.isascii() or not channel.isdigit() or not 15<=len(channel)<=22:
                        raise ValueError('Select a synced Discord channel or enter a valid channel ID to publish the dungeon roster.')
                    dup=db.execute("SELECT 1 FROM guild_events WHERE kind='dungeon' AND status IN ('queued','posting','posted','full','started') AND json_extract(config_json,'$.leader_id')=?",(uid,)).fetchone()
                    if dup:raise ValueError('You already have an active dungeon group. Close it before creating another.')
                    gid=make_dungeon_post(db,title=dungeon,leader_id=uid,leader_toon=toon,cls=cls,role=role,channel_id=channel,description=notes)
                    target=url_for('hub.group',event_id=gid)
                else:
                    zone=_clean(request.form.get('zone'),100,'Zone')
                    quest=_clean(request.form.get('quest_name'),110,'Quest',False) if kind=='questing' else ''
                    minimum=_level(request.form.get('min_level'),'minimum level')
                    maximum=_level(request.form.get('max_level'),'maximum level')
                    if maximum<minimum:raise ValueError('Maximum level must be at least minimum level.')
                    capacity=int(request.form.get('capacity','5'))
                    if not 2<=capacity<=5:raise ValueError('Group size must be between 2 and 5 players.')
                    notes=_clean(request.form.get('notes'),600,'Notes',False)
                    title=(f'{quest} — {zone}' if quest else f'{zone} {kind}')[:100]
                    gid=db.execute('''INSERT INTO instant_groups(kind,leader_id,title,zone,quest_name,min_level,max_level,capacity,notes)
                        VALUES(?,?,?,?,?,?,?,?,?)''',(kind,uid,title,zone,quest,minimum,maximum,capacity,notes)).lastrowid
                    db.execute('INSERT INTO instant_group_members(group_id,member_id,character_name,class_name,level) VALUES(?,?,?,?,?)',
                        (gid,uid,toon,cls,minimum))
                    target=url_for('groups.detail',group_id=gid)
            flash('Dungeon recruitment queued for Discord.' if kind=='dungeon' else 'Your group is now listed in Find Groups.','success')
            return redirect(target)
        except (ValueError,TypeError,sqlite3.Error) as exc:
            flash(str(exc),'error');return redirect(url_for('groups.home'))

    @bp.route('/groups/<int:group_id>',methods=['GET','POST'])
    def detail(group_id):
        uid=str(g.dashboard_access['discord_id'])
        with connect() as db:
            entry=db.execute('SELECT * FROM instant_groups WHERE id=?',(group_id,)).fetchone()
            if not entry:abort(404)
            data=dict(entry)
            chars=owned(db,uid)
            members=[dict(x) for x in db.execute('SELECT * FROM instant_group_members WHERE group_id=? ORDER BY joined_at',(group_id,))]
        mine=next((p for p in members if p['member_id']==uid),None)
        can_manage=(data['leader_id']==uid or g.dashboard_access['level'] in ('owner','pope') or 'group_roster_manage' in g.dashboard_access['permissions'])
        with connect() as db:
            roster=[dict(r) for r in db.execute('SELECT member_id,display_name FROM member_directory WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE LIMIT 700')]
        if request.method=='POST':
            action=request.form.get('action','')
            try:
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    current=db.execute('SELECT * FROM instant_groups WHERE id=?',(group_id,)).fetchone()
                    if not current:abort(404)
                    count=db.execute('SELECT COUNT(*) FROM instant_group_members WHERE group_id=?',(group_id,)).fetchone()[0]
                    present=db.execute('SELECT 1 FROM instant_group_members WHERE group_id=? AND member_id=?',(group_id,uid)).fetchone()
                    if action=='delete':
                        if not can_manage:abort(403)
                        if request.form.get('confirm','')!=str(group_id):raise ValueError('Enter the group ID to confirm deletion.')
                        db.execute('DELETE FROM instant_group_members WHERE group_id=?',(group_id,))
                        db.execute('DELETE FROM instant_groups WHERE id=?',(group_id,))
                        flash('Group deleted.','success')
                        return redirect(url_for('groups.home'))
                    elif action=='close':
                        if not can_manage:abort(403)
                        db.execute("UPDATE instant_groups SET status='closed' WHERE id=?",(group_id,))
                    elif action=='remove':
                        target=request.form.get('member_id','').strip()
                        if not can_manage:abort(403)
                        if target==current['leader_id'] or not target.isascii() or not target.isdecimal():abort(400)
                        db.execute('DELETE FROM instant_group_members WHERE group_id=? AND member_id=?',(group_id,target))
                    elif action=='add':
                        if not can_manage:abort(403)
                        if current['status']!='open' or count>=current['capacity']:raise ValueError('The group is closed or full.')
                        target=request.form.get('member_id','').strip()
                        if not target.isascii() or not target.isdecimal() or len(target)>20:abort(400)
                        if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(target,)).fetchone():raise ValueError('Select a current guild member.')
                        if db.execute('SELECT 1 FROM instant_group_members WHERE group_id=? AND member_id=?',(group_id,target)).fetchone():raise ValueError('Member already joined.')
                        toon=_clean(request.form.get('character_name',''),40,'Character')
                        cls=request.form.get('class_name','')
                        if cls not in CLASS_ROLES:raise ValueError('Choose a valid class.')
                        lvl=_level(request.form.get('level'),'level')
                        if not current['min_level']<=lvl<=current['max_level']:raise ValueError('Level is outside this group’s range.')
                        db.execute('INSERT INTO instant_group_members(group_id,member_id,character_name,class_name,level) VALUES(?,?,?,?,?)',(group_id,target,toon,cls,lvl))
                    elif action=='leave':
                        if current['leader_id']==uid:raise ValueError('Group leaders must close their group rather than leave.')
                        if not present:raise ValueError('You are not in this group.')
                        db.execute('DELETE FROM instant_group_members WHERE group_id=? AND member_id=?',(group_id,uid))
                    elif action=='join':
                        if current['status']!='open':raise ValueError('This group is closed.')
                        if present:raise ValueError('You are already in this group.')
                        if count>=current['capacity']:raise ValueError('This group is full.')
                        char_id=request.form.get('character_id','')
                        char=next((c for c in owned(db,uid) if str(c['id'])==char_id),None)
                        if not char:raise ValueError('Choose one of your registered characters.')
                        lvl=_level(request.form.get('level'),'character level')
                        if not current['min_level']<=lvl<=current['max_level']:raise ValueError('This character is outside the group’s requested level range.')
                        db.execute('INSERT INTO instant_group_members(group_id,member_id,character_name,class_name,level) VALUES(?,?,?,?,?)',
                            (group_id,uid,char['name'],char['class_name'],lvl))
                        notify(db,current['leader_id'],uid,'group','A guildmate joined your group',f'{char["name"]} joined {current["title"]}.',url_for('groups.detail',group_id=group_id))
                    else:abort(400)
                flash('Group updated.','success')
            except ValueError as exc:flash(str(exc),'error')
            return redirect(url_for('groups.detail',group_id=group_id))
        return render_template('group_detail.html',item=data,members=members,mine=mine,characters=chars,is_leader=data['leader_id']==uid,can_manage=can_manage,roster=roster,classes=CLASS_ROLES)
    return bp
