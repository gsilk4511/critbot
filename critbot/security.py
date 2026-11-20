"""Discord OAuth2 login and per-person permissions for the guild dashboard.

Required: DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI,
CRITBOT_OWNER_DISCORD_ID, CRITBOT_GUILD_ID, CRITBOT_DASHBOARD_SECRET.
OAuth sign-in requires HTTPS for remotely served deployments.
"""
import os, secrets, hmac, json, sqlite3
from datetime import datetime, timezone, timedelta
from functools import wraps
from contextlib import contextmanager
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from flask import request, session, redirect, url_for, abort, jsonify, render_template, flash, g
from .paths import database_path

API = 'https://discord.com/api/v10'
# Capabilities correspond to implemented server-side routes, not fictional departments.
# Viewing a section never implicitly grants permission to change it.
# Explicit capabilities map to real dashboard actions.  A view grant never implies write.
PERMISSIONS = (
    'achievements','achievement_editor','achievement_delete','awards','bulk_awards','automation',
    'events','events_create','events_manage','events_delete',
    'suggestions','suggestions_manage','suggestions_board','suggestions_archive','suggestions_delete',
    'conduct','conduct_manage','treasury','treasury_manage','involvement_view','involvement_handle',
    'stats','exports','competitions','branding','feedback_manage','member_notes','member_staff','member_profile_edit','guild_rank_manage','character_role_manage','group_roster_manage',
)
PERMISSION_GROUPS = (
    ('Guild operations', (
        ('events','View calendar & RSVPs','See event details, schedule and attendance.'),
        ('events_create','Create events','Add guild events and schedule drafts.'),
        ('events_manage','Edit & publish events','Edit event details, publish to Discord, manage attendance and cancel.'),
        ('events_delete','Delete events','Permanently remove events and associated Discord posts.'),
        ('conduct','View conduct log','Read private staff notes and follow-ups.'),
        ('conduct_manage','Manage conduct log','Record incidents, update follow-ups and close cases.'),
        ('treasury','View treasury','See guild resource ledger and balance.'),
        ('treasury_manage','Record treasury transactions','Add deposits, withdrawals and corrections.'),
        ('involvement_view','Read involvement responses','Review private member questionnaire answers.'),
        ('involvement_handle','Handle involvement responses','Set status, assign reviewers and leave private notes.'),
    )),
    ('Community & suggestions', (
        ('feedback_manage','Review private feedback','View member feedback and update its status.'),
        ('suggestions','View suggestions','See Discord submissions, votes and decisions.'),
        ('suggestions_manage','Triage suggestions','Assign priority and owner, post decisions to Discord.'),
        ('suggestions_board','Publish suggestion board','Choose Discord channel for idea submission.'),
        ('suggestions_archive','Archive / restore ideas','Hide suggestions from the active inbox and reopen them later.'),
        ('suggestions_delete','Permanently delete ideas','Remove suggestions and their Discord posts after explicit confirmation. High-trust permission.'),
        ('stats','View roster & activity','Read member statistics and rankings.'),
        ('member_notes','New-member follow-up notes','Read and write member welcome, orientation and recruitment notes.'),
        ('member_profile_edit','Edit member public profiles','Help members update their public character/profile fields.'),
        ('guild_rank_manage','Assign displayed guild ranks','Set the official rank shown on member profiles; does not change WoW.'),
        ('character_role_manage','Edit character roles','Change Tank, Healer and DPS eligibility on other members’ characters.'),
        ('group_roster_manage','Manage player groups','Manually add/remove players and delete player-created groups.'),
        ('member_staff','Private officer notes','Read and edit sensitive internal guild officer notes. Not included in onboarding access.'),
        ('exports','Export member data','Download member activity and achievement data.'),
    )),
    ('CritBot systems', (
        ('achievements','View achievements','Browse achievements and collections.'),
        ('achievement_editor','Design achievements','Create/edit achievements, rewards and rarity.'),
        ('achievement_delete','Delete achievements','Permanently remove achievements and related records. Restricted by default.'),
        ('awards','Award/revoke','Queue awards or revocations for one member.'),
        ('bulk_awards','Bulk awards','Queue high-volume achievement changes.'),
        ('automation','Automatic achievements','Configure tracking rules and milestones.'),
        ('competitions','Activity competitions','Start and finish competitions.'),
        ('branding','Card branding','Change achievement card look.'),
    )),
)
PRESETS = {
 'viewer': ('events','suggestions','stats'),
 'community': ('events','events_create','suggestions','suggestions_manage','suggestions_archive','member_notes','stats'),
 'welcome_team': ('member_notes','stats','suggestions'),
 'event_host': ('events','events_create','events_manage','suggestions'),
 'treasurer': ('treasury','treasury_manage','events','stats'),
 'involvement_reviewer': ('involvement_view',),
 'involvement_coordinator': ('involvement_view','involvement_handle'),
 'achievement_manager': ('achievements','achievement_editor','awards','stats'),
 'department_lead': ('events','events_create','events_manage','suggestions','suggestions_manage','suggestions_archive','member_notes','member_profile_edit','member_staff','conduct','conduct_manage','treasury','stats'),
}
PREREQUISITES={
 'achievement_editor':'achievements','awards':'achievements','bulk_awards':'achievements','automation':'achievements',
 'events_create':'events','events_manage':'events','events_delete':'events',
 'suggestions_manage':'suggestions','suggestions_board':'suggestions',
 'suggestions_archive':'suggestions','suggestions_delete':'suggestions',
 'conduct_manage':'conduct','treasury_manage':'treasury','involvement_handle':'involvement_view','exports':'stats',
}
# Applied ONCE in init_access to rows written by old releases. New grants never auto-escalate.
LEGACY_GRANTS={
 'achievements':('achievements','achievement_editor','awards','bulk_awards'),
 'events':('events','events_create','events_manage','events_delete'),
 'suggestions':('suggestions','suggestions_manage','suggestions_board'),
 'members':('stats',),'stats':('stats',),'automation':('automation',),
 'branding':('branding','competitions'),'exports':('exports',),
 'conduct':('conduct',),'treasury':('treasury',),
}
def expand_permissions(values):
    chosen=set(values)&set(PERMISSIONS)
    for write,view in PREREQUISITES.items():
        if write in chosen:chosen.add(view)
    return tuple(p for p in PERMISSIONS if p in chosen)


@contextmanager
def db_open():
    db = sqlite3.connect(database_path(), timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def init_access():
    with db_open() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS dashboard_access (
            discord_id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '',
            level TEXT NOT NULL DEFAULT 'officer' CHECK(level IN ('officer','pope')),
            permissions TEXT NOT NULL DEFAULT '[]', granted_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS dashboard_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL,
            target_id TEXT NOT NULL, action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '', recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS dashboard_schema_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)''')
        if not db.execute("SELECT 1 FROM dashboard_schema_meta WHERE key='permissions_v2'").fetchone():
            for row in db.execute('SELECT discord_id,permissions FROM dashboard_access').fetchall():
                try: old=json.loads(row['permissions'])
                except (ValueError,TypeError): old=[]
                upgraded=set()
                if isinstance(old,list):
                    for k in old: upgraded.update(LEGACY_GRANTS.get(k,()))
                upgraded=expand_permissions(upgraded)
                db.execute('UPDATE dashboard_access SET permissions=? WHERE discord_id=?',
                           (json.dumps(upgraded),row['discord_id']))
            db.execute("INSERT INTO dashboard_schema_meta(key,value) VALUES('permissions_v2','1')")
        if not db.execute("SELECT 1 FROM dashboard_schema_meta WHERE key='member_access_v1'").fetchone():
            for row in db.execute("SELECT discord_id,permissions FROM dashboard_access WHERE level='officer'").fetchall():
                try: old=set(json.loads(row['permissions']))
                except (ValueError,TypeError):old=set()
                old.update(('member_staff','member_profile_edit'))
                db.execute('UPDATE dashboard_access SET permissions=? WHERE discord_id=?',(json.dumps(expand_permissions(old)),row['discord_id']))
            db.execute("INSERT INTO dashboard_schema_meta(key,value) VALUES('member_access_v1','1')")


def config_ok():
    keys = ('DISCORD_CLIENT_ID','DISCORD_CLIENT_SECRET','DISCORD_REDIRECT_URI','CRITBOT_OWNER_DISCORD_ID','CRITBOT_GUILD_ID','CRITBOT_DASHBOARD_SECRET')
    return all(bool(os.getenv(k)) for k in keys) and len(os.getenv('CRITBOT_DASHBOARD_SECRET','')) >= 32


def api_get(url, token):
    req = Request(url, headers={'Authorization': f'Bearer {token}', 'User-Agent':'Critbot Guild Edition (Discord OAuth)'})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def exchange(code):
    payload = urlencode({'client_id':os.environ['DISCORD_CLIENT_ID'],
        'client_secret':os.environ['DISCORD_CLIENT_SECRET'],
        'grant_type':'authorization_code', 'code':code,
        'redirect_uri':os.environ['DISCORD_REDIRECT_URI']}).encode()
    req = Request(f'{API}/oauth2/token', data=payload,
        headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'Critbot Guild Edition'})
    with urlopen(req, timeout=10) as response:
        return json.load(response)['access_token']


def current_access():
    uid = session.get('discord_id')
    if not uid: return None
    if uid == os.getenv('CRITBOT_OWNER_DISCORD_ID'):
        return {'discord_id':uid,'level':'owner','permissions':PERMISSIONS,'display_name':session.get('display_name','Guild Master')}
    with db_open() as db:
        row = db.execute('SELECT * FROM dashboard_access WHERE discord_id=?',(uid,)).fetchone()
    if row is None:
        return {'discord_id':uid,'level':'member','permissions':(),
                'display_name':session.get('display_name') or 'Guild Member'}
    try:
        stored=json.loads(row['permissions'])
    except (TypeError, ValueError):
        stored=[]
    normalized=expand_permissions(stored)
    return {'discord_id':uid,'level':row['level'],
            'permissions':PERMISSIONS if row['level']=='pope' else normalized,
            'display_name':session.get('display_name') or row['display_name']}


def can(access, permission):
    return bool(access and (access['level'] in ('owner','pope') or permission in access['permissions']))


def needed(endpoint, method='GET', values=None, operation=None):
    name=endpoint or ''
    if name in ('login','oauth_start','oauth_callback','logout'):return None
    if name in ('access_page','access_save','access_remove'):return 'OFFICER_ADMIN'
    if name == 'command_center' or name.startswith(('hub.','characters.','requests.','social.','groups.')):return 'AUTHENTICATED'
    if name in ('about_version','feedback.home','channels.home','channels.refresh'):return 'AUTHENTICATED'
    if name in ('feedback.set_status','feedback.review'):return 'feedback_manage'
    if name=='channels.announcement':return 'OFFICER_ADMIN'
    if name in ('home','cards_page','card_preview'):return 'achievements'
    if name in ('new','edit','achievement_catalog','add_catalog_achievement'):return 'achievement_editor'
    if name == 'delete_achievement':return 'achievement_delete'
    if name in ('members_page','member_profile'):return 'AUTHENTICATED'
    if name=='member_rank_save':return 'guild_rank_manage'
    if name in ('member_self_save','member_staff_save','member_welcome_save','member_profile_studio','member_appearance_save'):return 'AUTHENTICATED'
    if name in ('member_action','member_state','member_actions','award','revoke'):return 'awards'
    if name in ('bulk','bulk_submit'):return 'bulk_awards'
    if name in ('stats_page','stats_member','leaderboards_page'):return 'stats'
    if name=='automatic_page':return 'automation'
    if name in ('events.home','events.detail'):return 'AUTHENTICATED'
    if name=='events.editor':
        return 'events_manage' if (values or {}).get('event_id') is not None else 'events_create'
    if name=='events.action':return 'events_delete' if operation=='delete' else 'events_manage'
    if name=='events.attendance':return 'events_manage'
    if name in ('suggestions.home','suggestions.detail','suggestions.create','suggestions.vote_web'):return 'AUTHENTICATED'
    if name in ('suggestions.update','suggestions.retry'):return 'suggestions_manage'
    if name in ('suggestions.archive','suggestions.restore'):return 'suggestions_archive'
    if name in ('suggestions.delete','suggestions.retry_delete'):return 'suggestions_delete'
    if name=='suggestions.board':return 'suggestions_board'
    if name=='operations.home':return 'conduct'
    if name in ('operations.create','operations.update'):return 'conduct_manage'
    if name=='operations.treasury_home':return 'treasury'
    if name=='operations.record':return 'treasury_manage'
    if name=='operations.treasury_export':return 'treasury'
    if name in ('involvement.form','involvement.submit'):return 'AUTHENTICATED'
    if name in ('involvement.review','involvement.export_csv'):return 'involvement_view'
    if name=='involvement.handle':return 'involvement_handle'
    if name=='version_save':return 'OFFICER_ADMIN'
    if name=='product.tools':return 'GUILD_TOOLS'
    if name=='product.export':return 'exports'
    if name=='product.brand':return 'branding'
    if name in ('product.seasons','product.close'):return 'competitions'
    return 'DENY'


def install(app):
    init_access()
    app.config.update(MAX_CONTENT_LENGTH=2*1024*1024,SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('CRITBOT_ALLOW_HTTP_LOCAL')!='1',
        PERMANENT_SESSION_LIFETIME=timedelta(days=30))

    def _deny_or_return_home():
        # Permissions are rechecked for every request. When a Pope revokes access
        # while someone is on a page, GET sends them somewhere they may still use.
        if request.method in ('GET','HEAD') and not request.is_json and not request.path.startswith('/api/'):
            flash('Your dashboard access has changed. You can still use your member profile and permitted tools.','error')
            return redirect(url_for('members_page'))
        if request.is_json or request.path.startswith('/api/'):
            return jsonify(error='Your access to this tool has changed.'),403
        return render_template('access_denied.html'),403

    @app.before_request
    def protect():
        if request.endpoint=='static':return
        # Local preview entry is deliberately available only in loopback-only developer mode.
        if (request.endpoint=='dev_login' and app.config.get('CRITBOT_DEV_MODE')
                and request.remote_addr in ('127.0.0.1','::1')
                and request.host.split(':')[0] in ('127.0.0.1','localhost')):
            return
        if not config_ok():return 'Discord login configuration is incomplete. Check the server environment variables.',503
        if request.endpoint in ('login','oauth_start','oauth_callback'):
            return
        access=current_access()
        if not access:
            if request.path.startswith('/api/') or request.is_json:return jsonify(error='Officer login required'),401
            return redirect(url_for('login'))
        g.dashboard_access=access
        permission = needed(request.endpoint, request.method, request.view_args, request.form.get('operation') if request.method=='POST' and request.endpoint=='events.action' else None)
        if permission == 'AUTHENTICATED':
            pass
        elif permission == 'GUILD_TOOLS':
            if not any(can(access,p) for p in ('competitions','branding','exports')):
                return _deny_or_return_home()
        elif permission == 'OFFICER_ADMIN':
            if access['level'] not in ('owner','pope'):return _deny_or_return_home()
        elif permission == 'DENY' or (permission and not can(access,permission)):
            return _deny_or_return_home()
        if request.method not in ('GET','HEAD','OPTIONS'):
            supplied=request.headers.get('X-CSRF-Token') or request.form.get('_csrf','')
            expected=session.get('csrf','')
            if not expected or not hmac.compare_digest(supplied,expected):abort(403)

    @app.get('/login')
    def login():
        return render_template('login.html', error=request.args.get('error'))

    @app.get('/auth/discord')
    def oauth_start():
        state=secrets.token_urlsafe(32)
        session['oauth_state']=state
        session['oauth_remember']=request.args.get('remember')=='1'
        query=urlencode({'client_id':os.environ['DISCORD_CLIENT_ID'],
            'redirect_uri':os.environ['DISCORD_REDIRECT_URI'],
            'response_type':'code','scope':'identify guilds.members.read','state':state})
        return redirect('https://discord.com/oauth2/authorize?'+query)

    @app.get('/auth/discord/callback')
    def oauth_callback():
        state=session.pop('oauth_state',None)
        if not state or not hmac.compare_digest(state,request.args.get('state','')) or not request.args.get('code'):
            return redirect(url_for('login',error='Discord login was not verified.'))
        try:
            token=exchange(request.args['code'])
            user=api_get(API+'/users/@me',token)
            member=api_get(API+'/users/@me/guilds/'+os.environ['CRITBOT_GUILD_ID']+'/member',token)
        except (HTTPError, KeyError, OSError, ValueError):
            return redirect(url_for('login',error='Discord verification failed or you are not in the guild Discord.'))
        uid=str(user['id'])
        # Membership check comes from Discord itself; never trust client-supplied IDs or roles.
        if not isinstance(member,dict) or str(member.get('user',{}).get('id',uid))!=uid:
            return redirect(url_for('login',error='Guild membership could not be verified.'))
        display_name=str(member.get('nick') or user.get('global_name') or user.get('username') or uid)[:80]
        # Add the verified member on first login even if the periodic bot sync hasn't run.
        with db_open() as db:
            db.execute('''INSERT INTO member_directory(member_id,display_name,username,joined_at,is_bot)
                VALUES(?,?,?,?,0) ON CONFLICT(member_id) DO UPDATE SET
                display_name=excluded.display_name,username=excluded.username,last_seen=CURRENT_TIMESTAMP''',
                (uid,display_name,str(user.get('username') or uid)[:80],member.get('joined_at')))
        remember=bool(session.get('oauth_remember'))
        # Every *verified guild Discord member* can access the member directory and
        # their own profile. Only dashboard_access grants officer capabilities.
        session.clear()
        session['discord_id']=uid
        session['display_name']=display_name
        session['csrf']=secrets.token_urlsafe(32)
        session.permanent=remember
        access = current_access()
        return redirect(url_for('hub.home'))

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/access')
    def access_page():
        with db_open() as db:
            entries=[dict(r,perms=expand_permissions(json.loads(r['permissions']))) for r in db.execute('SELECT * FROM dashboard_access ORDER BY CASE level WHEN "pope" THEN 0 ELSE 1 END,display_name')]
        with db_open() as db:
            roster=db.execute("SELECT member_id,display_name,username FROM member_directory WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE LIMIT 5000").fetchall()
        with db_open() as db:
            audit=db.execute('SELECT actor_id,target_id,action,detail,recorded_at FROM dashboard_audit ORDER BY id DESC LIMIT 25').fetchall()
        return render_template('access.html',entries=entries,roster=roster,groups=PERMISSION_GROUPS,
            presets=PRESETS,audit=audit,legacy_parser=expand_permissions,
            owner=os.environ['CRITBOT_OWNER_DISCORD_ID'])

    @app.post('/access/save')
    def access_save():
        actor=g.dashboard_access
        uid=request.form.get('discord_id','').strip()
        level=request.form.get('level','officer')
        name=request.form.get('display_name','').strip()[:80]
        template=request.form.get('access_template','custom')
        if template not in (*PRESETS,'custom','pope'):abort(400)
        raw_permissions=request.form.getlist('permissions')
        requested=set(raw_permissions)
        if requested-set(PERMISSIONS):abort(400)
        requested=set(expand_permissions(requested))
        if level=='officer' and (not requested or template=='pope'):abort(400)
        if level=='pope' and template not in ('pope','custom'):abort(400)
        if not uid.isascii() or not uid.isdecimal() or not 15<=len(uid)<=20 or uid==os.environ['CRITBOT_OWNER_DISCORD_ID'] or level not in ('officer','pope') :abort(400)
        # Only the owner can grant, edit or revoke Pope privileges.
        with db_open() as db:
            previous=db.execute('SELECT level FROM dashboard_access WHERE discord_id=?',(uid,)).fetchone()
            if (level=='pope' or (previous and previous['level']=='pope')) and actor['level']!='owner':abort(403)
            db.execute('''INSERT INTO dashboard_access(discord_id,display_name,level,permissions,granted_by)
                VALUES(?,?,?,?,?) ON CONFLICT(discord_id) DO UPDATE SET display_name=excluded.display_name,
                level=excluded.level,permissions=excluded.permissions,granted_by=excluded.granted_by,updated_at=CURRENT_TIMESTAMP''',
                (uid,name or uid,level,json.dumps(sorted(requested)),actor['discord_id']))
            db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                (actor['discord_id'],uid,'access_saved',json.dumps({'level':level,'template':template,'permissions':sorted(requested)})))
        flash('Dashboard access updated.','success')
        return redirect(url_for('access_page'))

    @app.post('/access/remove')
    def access_remove():
        uid=request.form.get('discord_id','').strip()
        actor=g.dashboard_access
        if uid==os.getenv('CRITBOT_OWNER_DISCORD_ID') or not uid.isascii() or not uid.isdecimal():abort(403)
        with db_open() as db:
            row=db.execute('SELECT level FROM dashboard_access WHERE discord_id=?',(uid,)).fetchone()
            if row and row['level']=='pope' and actor['level']!='owner':abort(403)
            db.execute('DELETE FROM dashboard_access WHERE discord_id=?',(uid,))
            db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action) VALUES(?,?,?)',(actor['discord_id'],uid,'access_removed'))
        flash('Dashboard access revoked.','success')
        return redirect(url_for('access_page'))

    @app.context_processor
    def security_context():
        access=current_access()
        return dict(hosted_mode=True,csrf_token=session.get('csrf',''),viewer=access,
                    can_access=lambda p:can(access,p))
