"""Member-facing first visit and personalized Guild Hub.

Purely guild data driven; recommendations are sorted by declared interests and
confirmed activity, never inferred from private Discord data. No background DM
notifications are sent by this module.
"""
from datetime import datetime, timezone
import json

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from .features.events.store import CLASS_ROLES, describe, signup
from .characters import owned as owned_characters, add as add_character
from .group_finder import find_groups as find_instant_groups

INTERESTS = (
    ('Dungeons', '⚔', 'Find open dungeon roles'),
    ('Guild Events', '✦', 'Races, competitions, and hangouts'),
    ('Raids', '🛡', 'Sign up for organized raiding'),
    ('PvP', '⚑', 'Find battleground and PvP groups'),
    ('Crafting', '⚒', 'Help guildmates with professions'),
    ('Just Hanging Out', '☕', 'Meet people and enjoy the guild'),
)
VALID_INTERESTS = {item[0] for item in INTERESTS}


def init_hub(db):
    db.execute('''CREATE TABLE IF NOT EXISTS member_hub_settings(
        member_id TEXT PRIMARY KEY,
        interests_json TEXT NOT NULL DEFAULT '[]',
        character_name TEXT NOT NULL DEFAULT '',
        character_class TEXT NOT NULL DEFAULT '',
        notify_opt_in INTEGER NOT NULL DEFAULT 0,
        onboarded INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    existing={r[1] for r in db.execute('PRAGMA table_info(member_hub_settings)')}
    for column,definition in (('theme',"TEXT NOT NULL DEFAULT 'ember'"),('density',"TEXT NOT NULL DEFAULT 'comfortable'"),('hub_layout',"TEXT NOT NULL DEFAULT 'balanced'"),('notify_requests','INTEGER NOT NULL DEFAULT 1'),('notify_groups','INTEGER NOT NULL DEFAULT 1'),('notify_events','INTEGER NOT NULL DEFAULT 1'),('notify_commendations','INTEGER NOT NULL DEFAULT 1'),('notify_social','INTEGER NOT NULL DEFAULT 0'),('show_community','INTEGER NOT NULL DEFAULT 1'),('compact_sidebar','INTEGER NOT NULL DEFAULT 0')):
        if column not in existing: db.execute(f'ALTER TABLE member_hub_settings ADD COLUMN {column} {definition}')


def _preferences(db, member_id):
    result = db.execute('SELECT * FROM member_hub_settings WHERE member_id=?', (member_id,)).fetchone()
    if result is None:
        return {'interests': ['Dungeons', 'Guild Events'], 'character_name':'', 'character_class':'',
                'notify_opt_in':False, 'onboarded':False,'theme':'ember','density':'comfortable','hub_layout':'balanced','notify_requests':1,'notify_groups':1,'notify_events':1,'notify_commendations':1,'notify_social':0,'show_community':1,'compact_sidebar':0}
    row=dict(result)
    try: interests=json.loads(row['interests_json'])
    except (ValueError, TypeError): interests=[]
    row['interests']=[i for i in interests if i in VALID_INTERESTS]
    return row


def _group_data(db, member_id):
    events=db.execute("""SELECT * FROM guild_events WHERE kind='dungeon' AND status IN ('queued','posting','posted','full','started') ORDER BY created_at DESC LIMIT 50""").fetchall()
    result=[]
    for event in events:
        item=describe(event)
        people=db.execute('SELECT choice,class_name,name,member_id FROM guild_event_members WHERE event_id=? AND rsvp=?',(item['id'],'going')).fetchall()
        capacities={x['key']:x for x in item['config'].get('slots',[])}
        used={k:0 for k in capacities}
        for person in people:
            if person['choice'] in used:used[person['choice']]+=1
        slots=[{'key':key,'name':v['name'],'used':used[key],'capacity':v['capacity'],'open':max(0,v['capacity']-used[key])} for key,v in capacities.items()]
        item['slots']=slots
        item['open_count']=sum(x['open'] for x in slots)
        item['joined']=any(str(p['member_id'])==str(member_id) for p in people)
        item['link']=url_for('hub.group',event_id=item['id'])
        result.append(item)
    for row in find_instant_groups(db,member_id):
        item=dict(row)
        item.update(id=-item['id'],status='posted',is_instant=True,
                    slots=[dict(name='Players',used=item['count'],capacity=item['capacity'],open=item['open_count'])])
        result.append(item)
    return sorted(result,key=lambda e:(not e['joined'],e['open_count']==0,-e['id']))


def _scheduled_data(db, member_id):
    now=datetime.now(timezone.utc)
    events=db.execute("""SELECT * FROM guild_events WHERE kind!='dungeon' AND status='posted' ORDER BY starts_at ASC LIMIT 80""").fetchall()
    results=[]
    for event in events:
        try: starts=datetime.fromisoformat(event['starts_at']).astimezone(timezone.utc)
        except (ValueError, TypeError): continue
        if starts<now:continue
        item=describe(event)
        item['joined']=bool(db.execute("SELECT 1 FROM guild_event_members WHERE event_id=? AND member_id=? AND rsvp='going'",(item['id'],member_id)).fetchone())
        results.append(item)
    return results[:8]


def blueprint(connect):
    bp=Blueprint('hub',__name__)

    @bp.route('/hub/welcome',methods=['GET','POST'])
    def welcome():
        me=g.dashboard_access['discord_id']
        with connect() as db: pref=_preferences(db,me)
        if request.method=='POST':
            choices=request.form.getlist('interests')
            if len(choices)>len(INTERESTS) or len(set(choices))!=len(choices) or any(i not in VALID_INTERESTS for i in choices):abort(400)
            toon=request.form.get('character_name','').strip()
            cls=request.form.get('character_class','').strip()
            if len(toon)>40 or len(toon)>0 and len(toon)<2:abort(400)
            if toon and cls not in CLASS_ROLES:abort(400)
            if not toon:cls=''
            notice=int(request.form.get('notify_opt_in')=='on')
            with connect() as db:
                db.execute('''INSERT INTO member_hub_settings(member_id,interests_json,character_name,character_class,notify_opt_in,onboarded)
                    VALUES(?,?,?,?,?,1) ON CONFLICT(member_id) DO UPDATE SET
                    interests_json=excluded.interests_json,character_name=excluded.character_name,
                    character_class=excluded.character_class,notify_opt_in=excluded.notify_opt_in,
                    onboarded=1,updated_at=CURRENT_TIMESTAMP''',(me,json.dumps(choices),toon,cls,notice))
                if toon:
                    try: add_character(db,me,toon,cls)
                    except ValueError as exc: abort(400, description=str(exc))
                db.execute('''INSERT INTO member_profiles(member_id,main_character,main_class,interests) VALUES(?,?,?,?)
                    ON CONFLICT(member_id) DO UPDATE SET
                    main_character=CASE WHEN main_character='' THEN excluded.main_character ELSE main_character END,
                    main_class=CASE WHEN main_class='' THEN excluded.main_class ELSE main_class END,
                    interests=CASE WHEN interests='' THEN excluded.interests ELSE interests END''',(me,toon,cls,', '.join(choices)))
            flash('Your Guild Hub is ready. You can change these preferences anytime.','success')
            return redirect(url_for('hub.home'))
        return render_template('hub_onboarding.html',pref=pref,interests=INTERESTS,classes=tuple(CLASS_ROLES),editing=bool(pref['onboarded']))

    @bp.route('/hub/settings',methods=['GET','POST'])
    def settings():
        me=g.dashboard_access['discord_id']
        if request.method=='POST':
            theme=request.form.get('theme','ember')
            density=request.form.get('density','comfortable')
            layout=request.form.get('hub_layout','balanced')
            if theme not in ('ember','midnight','forest') or density not in ('comfortable','compact') or layout not in ('balanced','action-first'):abort(400)
            values={key:int(request.form.get(key)=='on') for key in ('notify_requests','notify_groups','notify_events','notify_commendations','notify_social','show_community','compact_sidebar')}
            selected=request.form.getlist('interests')
            if len(selected)>len(INTERESTS) or len(set(selected))!=len(selected) or any(i not in VALID_INTERESTS for i in selected):abort(400)
            with connect() as db:
                db.execute('''INSERT INTO member_hub_settings(member_id,interests_json,onboarded) VALUES(?,?,1)
                ON CONFLICT(member_id) DO NOTHING''',(me,json.dumps(selected)))
                db.execute('''UPDATE member_hub_settings SET interests_json=?,theme=?,density=?,hub_layout=?,notify_requests=?,notify_groups=?,notify_events=?,notify_commendations=?,notify_social=?,show_community=?,compact_sidebar=?,updated_at=CURRENT_TIMESTAMP WHERE member_id=?''',
                  (json.dumps(selected),theme,density,layout,*(values[k] for k in ('notify_requests','notify_groups','notify_events','notify_commendations','notify_social','show_community','compact_sidebar')),me))
            flash('Your dashboard settings are saved.','success')
            return redirect(url_for('hub.settings'))
        with connect() as db:pref=_preferences(db,me)
        return render_template('hub_settings.html',pref=pref,interests=INTERESTS)

    @bp.get('/hub')
    def home():
        me=g.dashboard_access['discord_id']
        with connect() as db:
            pref=_preferences(db,me)
            if not pref['onboarded']:return redirect(url_for('hub.welcome'))
            groups=_group_data(db,me)
            events=_scheduled_data(db,me)
            unlocked=db.execute('''SELECT a.name,a.rarity,a.icon,u.awarded_at FROM unlocks u
                JOIN achievements a ON u.achievement_id=a.id WHERE u.member_id=?
                ORDER BY u.awarded_at DESC LIMIT 3''',(me,)).fetchall()
            completed=db.execute('SELECT COUNT(*) FROM unlocks WHERE member_id=?',(me,)).fetchone()[0]
            member=db.execute('SELECT display_name FROM member_directory WHERE member_id=?',(me,)).fetchone()
            name=member['display_name'] if member else g.dashboard_access['display_name']
            recent_orders=[dict(r) for r in db.execute("SELECT * FROM guild_requests WHERE (requester_id=? OR helper_id=?) AND status IN ('claimed','delivered') ORDER BY id DESC LIMIT 4",(me,me))]
            hub_open_orders=[dict(r) for r in db.execute("""SELECT r.*,m.display_name requester_name FROM guild_requests r LEFT JOIN member_directory m ON m.member_id=r.requester_id WHERE r.status='open' AND r.requester_id<>? ORDER BY r.id DESC LIMIT 5""",(me,))]
            notifications=[dict(r) for r in db.execute("SELECT id,title,message,link FROM hub_notifications WHERE recipient_id=? AND read_at IS NULL ORDER BY id DESC LIMIT 2",(me,))]
            request_opportunities=db.execute("SELECT COUNT(*) FROM guild_requests WHERE status='open' AND requester_id<>?",(me,)).fetchone()[0]
            characters=owned_characters(db,me)
            # Public peer feedback only; never show private officer notes or infer a member's character.
            community_members=[dict(row) for row in db.execute("""SELECT m.member_id,m.display_name,
                (SELECT COUNT(*) FROM member_commendations c WHERE c.target_id=m.member_id) votes,
                (SELECT c.trait FROM member_commendations c WHERE c.target_id=m.member_id
                 GROUP BY c.trait ORDER BY COUNT(*) DESC,c.trait LIMIT 1) best_trait
                FROM member_directory m WHERE m.is_bot=0 AND m.member_id<>?
                ORDER BY votes DESC,m.display_name COLLATE NOCASE LIMIT 3""",(me,))]
        interests=set(pref['interests'])
        # Commitments always precede recommendations, irrespective of stated interests.
        my_groups=[e for e in groups if e['joined']]
        my_events=[e for e in events if e['joined']]
        recommendations=[]
        if 'Dungeons' in interests:
            recommendations.extend({'type':'group','obj':e} for e in groups if not e['joined'] and e['open_count']>0)
        if 'Guild Events' in interests or 'Raids' in interests or 'Just Hanging Out' in interests:
            for e in events:
                if e['joined']:continue
                if 'Raids' in interests and e['kind']=='raid' or 'Guild Events' in interests and e['kind'] in ('general','custom') or 'Just Hanging Out' in interests and e['kind']=='general':
                    recommendations.append({'type':'event','obj':e})
        if not recommendations:
            # Avoid an empty homepage, but explain when general results are shown.
            recommendations.extend({'type':'group','obj':e} for e in groups if not e['joined'] and e['open_count']>0)
            recommendations.extend({'type':'event','obj':e} for e in events if not e['joined'])
        return render_template('hub_home.html',pref=pref,name=name,groups=groups,events=events,
            my_groups=my_groups[:3],my_events=my_events[:3],recs=recommendations[:3],
            unlocked=unlocked,completed=completed,classes=CLASS_ROLES,
            recent_orders=recent_orders,request_opportunities=request_opportunities,characters=characters,community_members=community_members,hub_open_orders=hub_open_orders,notifications=notifications)

    @bp.route('/hub/groups/<int:event_id>',methods=['GET','POST'])
    def group(event_id):
        me=g.dashboard_access['discord_id']
        with connect() as db:
            pref=_preferences(db,me)
            characters=owned_characters(db,me)
            raw=db.execute('SELECT * FROM guild_events WHERE id=? AND kind=?',(event_id,'dungeon')).fetchone()
            if not raw or raw['status'] not in ('queued','posting','posted','full','started'):abort(404)
            e=describe(raw)
            people=db.execute("SELECT * FROM guild_event_members WHERE event_id=? AND rsvp='going' ORDER BY updated_at",(event_id,)).fetchall()
            mine=next((dict(p) for p in people if str(p['member_id'])==str(me)),None)
            can_manage=(str(e['config'].get('leader_id'))==str(me) or g.dashboard_access['level'] in ('owner','pope') or 'group_roster_manage' in g.dashboard_access['permissions'])
            roster=[dict(r) for r in db.execute('SELECT member_id,display_name FROM member_directory WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE LIMIT 700')]
            slots=[]
            for slot in e['config'].get('slots',[]):
                players=[dict(p) for p in people if p['choice']==slot['key']]
                slots.append(dict(slot,players=players,open=max(0,slot['capacity']-len(players))))
        if request.method=='POST':
            intent=request.form.get('intent','')
            if intent=='delete':
                if not can_manage:abort(403)
                if request.form.get('confirm')!=str(event_id):
                    flash('Type the group ID to confirm deletion.','error')
                    return redirect(url_for('hub.group',event_id=event_id))
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    fresh=db.execute('SELECT status,message_id FROM guild_events WHERE id=? AND kind=?',(event_id,'dungeon')).fetchone()
                    if not fresh:abort(404)
                    if fresh['status'] in ('deleting','delete_failed'):abort(409)
                    if fresh['message_id']:
                        db.execute("UPDATE guild_events SET status='deleting',last_error='',revision=revision+1 WHERE id=?",(event_id,))
                    else:
                        db.execute('DELETE FROM guild_event_members WHERE event_id=?',(event_id,))
                        db.execute('DELETE FROM guild_events WHERE id=?',(event_id,))
                flash('Group deletion queued for Discord sync.' if raw['message_id'] else 'Group deleted.','success')
                return redirect(url_for('groups.home'))
            if intent in ('remove','add') and not can_manage:abort(403)
            if raw['status'] not in ('posted','full'):
                flash('This group is not accepting roster changes yet.','error')
                return redirect(url_for('hub.group',event_id=event_id))
            if request.form.get('intent')=='remove':
                member_id=request.form.get('member_id','').strip()
                if member_id==str(e['config'].get('leader_id')) or not member_id.isascii() or not member_id.isdecimal():abort(400)
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    removed=db.execute("UPDATE guild_event_members SET rsvp='declined',choice='',class_name='',updated_at=CURRENT_TIMESTAMP WHERE event_id=? AND member_id=? AND rsvp='going'",(event_id,member_id))
                    if removed.rowcount:db.execute('UPDATE guild_events SET revision=revision+1 WHERE id=?',(event_id,))
                flash('Member removed. Discord embed refresh is queued.','success')
                return redirect(url_for('hub.group',event_id=event_id))
            if intent=='add':
                member_id=request.form.get('member_id','').strip()
                toon=request.form.get('character_name','').strip()
                cls=request.form.get('character_class','').strip()
                role=request.form.get('role','').strip()
                if not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:abort(400)
                if not 2<=len(toon)<=40 or cls not in CLASS_ROLES or role not in CLASS_ROLES[cls]:
                    flash('Choose a character, class and compatible role.','error')
                    return redirect(url_for('hub.group',event_id=event_id))
                slot=next((v for v in slots if v['name']==role),None)
                if slot is None or slot['open']<1:
                    flash('That group role is full.','error')
                    return redirect(url_for('hub.group',event_id=event_id))
                try:
                    with connect() as db:
                        if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone():
                            raise ValueError('Select a current guild member.')
                        signup(db,event_id,member_id,toon,slot['key'],cls,raw['guild_id'],raw['channel_id'],raw['message_id'])
                    flash('Member added. Discord roster refresh queued.','success')
                except ValueError as exc:flash(str(exc),'error')
                return redirect(url_for('hub.group',event_id=event_id))
            if request.form.get('intent')=='leave':
                try:
                    with connect() as db:
                        signup(db,event_id,me,'',None,'',raw['guild_id'],raw['channel_id'],raw['message_id'])
                    flash('You left the dungeon group. The roster will update when the bot syncs.','success')
                except ValueError as exc:flash(str(exc),'error')
                return redirect(url_for('hub.group',event_id=event_id))
            toon=request.form.get('character_name','').strip()
            cls=request.form.get('character_class','').strip()
            role=request.form.get('role','').strip()
            char_id=request.form.get('character_id','').strip()
            if char_id:
                try: selected_id=int(char_id)
                except ValueError:abort(400)
                saved=next((c for c in characters if c['id']==selected_id),None)
                if not saved:abort(403)
                toon,cls=saved['name'],saved['class_name']
                if role not in saved['roles']:
                    flash('This character is not registered for that role. Update its roles in My Characters.','error')
                    return redirect(url_for('hub.group',event_id=event_id))

            if len(toon)<2 or len(toon)>40 or cls not in CLASS_ROLES or role not in CLASS_ROLES[cls]:
                flash('Enter a valid character name, class and compatible role.','error')
                return redirect(url_for('hub.group',event_id=event_id))
            choice=next((s['key'] for s in slots if s['name']==role),None)
            if not choice:abort(400)
            try:
                with connect() as db:
                    signup(db,event_id,me,toon,choice,cls,raw['guild_id'],raw['channel_id'],raw['message_id'])
                    add_character(db,me,toon,cls)
                    db.execute('''INSERT INTO member_hub_settings(member_id,character_name,character_class) VALUES(?,?,?)
                        ON CONFLICT(member_id) DO UPDATE SET
                        character_name=CASE WHEN character_name='' THEN excluded.character_name ELSE character_name END,
                        character_class=CASE WHEN character_class='' THEN excluded.character_class ELSE character_class END''',(me,toon,cls))
                    db.execute('''INSERT INTO member_profiles(member_id,main_character,main_class) VALUES(?,?,?)
                        ON CONFLICT(member_id) DO UPDATE SET
                        main_character=CASE WHEN main_character='' THEN excluded.main_character ELSE main_character END,
                        main_class=CASE WHEN main_class='' THEN excluded.main_class ELSE main_class END''',(me,toon,cls))
                flash('You joined the group! The bot will update its Discord roster when connected.','success')
                return redirect(url_for('hub.home') if request.form.get('origin')=='hub' else url_for('hub.group',event_id=event_id))
            except ValueError as exc:
                flash(str(exc),'error')
                return redirect(url_for('hub.group',event_id=event_id))
        return render_template('hub_group.html',event=e,slots=slots,mine=mine,pref=pref,classes=CLASS_ROLES,characters=characters,is_leader=str(e['config'].get('leader_id'))==str(me),can_manage=can_manage,roster=roster)

    return bp
