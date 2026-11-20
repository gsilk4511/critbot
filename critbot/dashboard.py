import os
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from flask import Flask, flash, redirect, render_template, request, url_for, abort, Response
from .cards import render_unlock_card
from .features.premium.product import blueprint as product_blueprint
from .features.premium.store import init_premium,allowed,plan,commercial,rule_limit,branding
from .security import install as install_security
from .features.events.store import init_events
from .features.suggestions.store import init_suggestions
from .features.operations.web import blueprint as operations_blueprint, init_operations
from .features.suggestions.web import blueprint as suggestion_blueprint
from .features.events.web import blueprint as event_blueprint
from .automatic_achievements import init_schema, KINDS
from .activity_stats import guild_roster, member_stats, member_progress
from .leaderboards import METRICS, ranked_members

from .paths import ROOT, database_path
from .release import delete_achievement_records
from .channel_overrides import init_channel_sync, parse_manual_ids
from .achievement_catalog import CATALOG, CATEGORIES, achievement_icon_html
from .profile_style import THEMES, BANNERS, LAYOUTS, AWARD_VIEWS, FRAMES, TYPOGRAPHY, ART_FILTERS, AVATARS, TROPHY_DENSITY, profile_defaults, read_showcase, PORTRAITS, EMBLEMS, PORTRAIT_GROUPS, STUDIO_BANNERS, STUDIO_MAIN_THEMES, STUDIO_OTHER_THEMES
BASE = ROOT
DB_PATH = database_path()
app = Flask(__name__, template_folder=str(BASE / 'templates'), static_folder=str(BASE / 'static'))
app.jinja_env.filters['achievement_icon'] = achievement_icon_html
app.secret_key = os.environ.get('CRITBOT_DASHBOARD_SECRET', 'CONFIGURE_DISCORD_LOGIN_SECRET')

from .version import VERSION, RELEASE, BUILD, NOTES, MILESTONES, CHANGES
from .hub import init_hub, blueprint as hub_blueprint
from .characters import init_characters, blueprint as characters_blueprint, owned as member_owned_characters
from .request_board import init_requests, blueprint as request_blueprint
from .social import init_social, blueprint as social_blueprint, commendation_summary, TRAITS
from .group_finder import init_groups, blueprint as groups_blueprint
from .involvement import init_involvement, blueprint as involvement_blueprint
from .guild_ranks import RANKS, RANK_STYLES

@app.context_processor
def release_display_context():
    return dict(dev_preview=os.environ.get('CRITBOT_DEV_PREVIEW')=='1')


def release_metadata():
    # A deployment declares the code version; owner-controlled notes are stored separately.
    try:
        with connect() as db:
            row=db.execute("SELECT version,title,notes,updated_at FROM critbot_release_override WHERE id=1").fetchone()
        if row:
            saved=dict(row)
            if saved['version']!=VERSION:
                # Do not allow a stale version override from a previous deployment to hide the actual installed version.
                return dict(version=VERSION,title=RELEASE,notes=saved['notes'],updated_at=saved['updated_at'])
            return saved
    except sqlite3.Error:pass
    return dict(version=VERSION,title=RELEASE,notes='',updated_at='')

@app.get('/about/version')
def about_version():
    return render_template('version.html',version=VERSION,release=RELEASE,build=BUILD,release_notes=NOTES,
        milestones=MILESTONES,changes=CHANGES,manual=release_metadata())

@app.post('/about/version/save')
def version_save():
    from flask import g
    version=request.form.get('version','').strip();title=request.form.get('title','').strip();notes=request.form.get('notes','').strip()
    if not 1<=len(version)<=24 or not 1<=len(title)<=100 or len(notes)>8000:abort(400)
    with connect() as db:
        db.execute("INSERT INTO critbot_release_override(id,version,title,notes,updated_by) VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,title=excluded.title,notes=excluded.notes,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP",(version,title,notes,g.dashboard_access['discord_id']))
        db.execute("INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,'release_notes_updated',?)",(g.dashboard_access['discord_id'],'critbot',version+' · '+title))
    flash('Public release label and notes updated. Code version remains '+VERSION+'.','success')
    return redirect(url_for('about_version'))

RARITIES = ('Common', 'Uncommon', 'Rare', 'Epic', 'Legendary')

@contextmanager
def connect():
    # SQLite's native 'with conn' commits but does NOT close the connection.
    # Close after every request to avoid lingering database locks on Unraid.
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

def init_db():
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            rarity TEXT NOT NULL DEFAULT 'Common',
            points INTEGER NOT NULL DEFAULT 10,
            icon TEXT NOT NULL DEFAULT '🏆',
            role_id TEXT NOT NULL DEFAULT '',
            beta_exclusive INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        achievement_columns={r[1] for r in db.execute('PRAGMA table_info(achievements)')}
        if 'category' not in achievement_columns:db.execute("ALTER TABLE achievements ADD COLUMN category TEXT NOT NULL DEFAULT 'Uncategorized'")
        if 'verification' not in achievement_columns:db.execute("ALTER TABLE achievements ADD COLUMN verification TEXT NOT NULL DEFAULT ''")
        db.execute('''CREATE TABLE IF NOT EXISTS unlocks (
            achievement_id INTEGER NOT NULL,
            member_id TEXT NOT NULL,
            awarded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (achievement_id, member_id),
            FOREIGN KEY (achievement_id) REFERENCES achievements(id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS award_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, achievement_id INTEGER NOT NULL,
            member_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        columns = {row[1] for row in db.execute('PRAGMA table_info(award_queue)')}
        if 'action' not in columns:
            db.execute("ALTER TABLE award_queue ADD COLUMN action TEXT NOT NULL DEFAULT 'award'")
        if 'silent' not in columns:
            db.execute("ALTER TABLE award_queue ADD COLUMN silent INTEGER NOT NULL DEFAULT 0")
        if 'batch_id' not in columns:
            db.execute("ALTER TABLE award_queue ADD COLUMN batch_id INTEGER")
        db.execute('''CREATE TABLE IF NOT EXISTS member_directory (
            member_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            username TEXT NOT NULL, joined_at TEXT, is_bot INTEGER NOT NULL DEFAULT 0,
            last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS bulk_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT, achievement_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, announcement_sent INTEGER NOT NULL DEFAULT 0
        )''')
        batch_columns = {row[1] for row in db.execute('PRAGMA table_info(bulk_batches)')}
        if 'action' not in batch_columns:
            db.execute("ALTER TABLE bulk_batches ADD COLUMN action TEXT NOT NULL DEFAULT 'award'")

    with connect() as db:
        init_schema(db)

    with connect() as db:
        init_events(db)
        init_suggestions(db)
        # Commit schema migrations before the next initializer takes an SQLite backup.
        # Backing up the same connection with uncommitted DDL can deadlock startup.
        db.commit()
        init_premium(db)
        init_operations(db)
        init_channel_sync(db)
        init_hub(db)
        from .feedback import init_feedback
        init_feedback(db)
        db.execute('''CREATE TABLE IF NOT EXISTS member_welcome_notes (
            member_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'Not contacted',
            notes TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS member_welcome_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, member_id TEXT NOT NULL,
            actor_id TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS member_profiles (
            member_id TEXT PRIMARY KEY, about TEXT NOT NULL DEFAULT '',
            main_character TEXT NOT NULL DEFAULT '', main_class TEXT NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '', availability TEXT NOT NULL DEFAULT '',
            goals TEXT NOT NULL DEFAULT '', staff_status TEXT NOT NULL DEFAULT 'No designation',
            staff_department TEXT NOT NULL DEFAULT '', staff_notes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            staff_updated_at TEXT)''')
        # Safe, additive migration: never replace existing member profiles or staff notes.
        columns={r[1] for r in db.execute('PRAGMA table_info(member_profiles)')}
        for name,decl in (
            ('tagline',"TEXT NOT NULL DEFAULT ''"),
            ('theme',"TEXT NOT NULL DEFAULT 'ember'"),
            ('banner',"TEXT NOT NULL DEFAULT 'flare'"),
            ('layout',"TEXT NOT NULL DEFAULT 'story'"),
            ('award_view',"TEXT NOT NULL DEFAULT 'featured'"),
            ('frame_style',"TEXT NOT NULL DEFAULT 'ornate'"),
            ('showcase_caption',"TEXT NOT NULL DEFAULT ''"),
            ('featured_achievements',"TEXT NOT NULL DEFAULT '[]'"),
            ('achievement_captions',"TEXT NOT NULL DEFAULT '{}'"),
            ('typography',"TEXT NOT NULL DEFAULT 'classic'"),
            ('art_filter',"TEXT NOT NULL DEFAULT 'balanced'"),
            ('avatar_style',"TEXT NOT NULL DEFAULT 'monogram'"),
            ('trophy_density',"TEXT NOT NULL DEFAULT 'balanced'"),
            ('portrait',"TEXT NOT NULL DEFAULT 'none'"),
            ('portrait_emblem',"TEXT NOT NULL DEFAULT 'none'"),
            ('guild_rank',"TEXT NOT NULL DEFAULT ''"),
            ('rank_style',"TEXT NOT NULL DEFAULT 'banner'")
        ):
            if name not in columns:db.execute(f'ALTER TABLE member_profiles ADD COLUMN {name} {decl}')
        init_characters(db)
        init_requests(db)
        init_social(db)
        init_groups(db)
        init_involvement(db)
        db.execute("""CREATE TABLE IF NOT EXISTS critbot_release_override (
          id INTEGER PRIMARY KEY CHECK(id=1),version TEXT NOT NULL,title TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',updated_by TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        from .achievement_catalog import install_catalog
        install_catalog(db)


install_security(app)
from .channel_controls import blueprint as channel_blueprint
app.register_blueprint(channel_blueprint(connect))
app.register_blueprint(groups_blueprint(connect))
from .feedback import blueprint as feedback_blueprint
app.register_blueprint(feedback_blueprint(connect))

@app.get('/command')
def command_center():
    """Officer landing screen: actionable cross-feature snapshot, not just achievements."""
    from .security import can, current_access
    from .features.events.store import describe
    access=current_access()
    if access and access['level']=='member':
        return redirect(url_for('members_page'))
    with connect() as db:
        count=lambda query:db.execute(query).fetchone()[0]
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc)
        scheduled=[r[0] for r in db.execute("SELECT starts_at FROM guild_events WHERE status NOT IN ('cancelled','completed','deleting')").fetchall()]
        upcoming=sum(1 for start in scheduled if datetime.fromisoformat(start).astimezone(timezone.utc)>=now)
        totals={
          'members':count('SELECT COUNT(*) FROM member_directory WHERE is_bot=0'),
          'achievements':count('SELECT COUNT(*) FROM achievements WHERE active=1'),
          'unlocks':count('SELECT COUNT(*) FROM unlocks'),
          'upcoming':upcoming,
          'ideas':count("SELECT COUNT(*) FROM guild_suggestions WHERE status='open'"),
        }
        events=[describe(e) for e in db.execute("SELECT * FROM guild_events WHERE status NOT IN ('completed','cancelled','deleting') ORDER BY starts_at ASC LIMIT 5")]
        suggestions=db.execute("SELECT id,title,status FROM guild_suggestions WHERE status IN ('open','planned') ORDER BY id DESC LIMIT 5").fetchall()
        conduct=count("SELECT COUNT(*) FROM conduct_cases WHERE status!='closed'") if can(access,'conduct') else None
        treasury=count('SELECT COUNT(*) FROM treasury_ledger') if can(access,'treasury') else None
    return render_template('command.html',totals=totals,events=events,suggestions=suggestions,
                           conduct_count=conduct,treasury_count=treasury)

@app.get('/')
def home():
    with connect() as db:
        items = db.execute("""SELECT a.*, COUNT(u.member_id) AS unlock_count
            FROM achievements a LEFT JOIN unlocks u ON a.id = u.achievement_id
            WHERE a.active=1 GROUP BY a.id ORDER BY a.name COLLATE NOCASE""").fetchall()
        members = db.execute("""SELECT member_id, display_name, username FROM member_directory
            WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE""").fetchall()
        unlocks = db.execute('SELECT achievement_id, member_id FROM unlocks').fetchall()
        pending = db.execute("""SELECT achievement_id, member_id, action FROM award_queue
            WHERE status='pending'""").fetchall()
    owned = {}
    for u in unlocks:
        owned.setdefault(str(u['member_id']), []).append(u['achievement_id'])
    waiting = {}
    for q in pending:
        waiting.setdefault(str(q['member_id']), {}).setdefault(q['action'], []).append(q['achievement_id'])
    return render_template('index.html', items=items, members=members,
        owned=owned, waiting=waiting, categories=CATEGORIES, achievement_data=[{key:a[key] for key in ('id','name','description','rarity','points','icon','category')} for a in items], total_unlocks=len(unlocks))

@app.post('/member-action')
def member_action():
    member_id = request.form.get('member_id', '').strip()
    achievement_id = request.form.get('achievement_id', '').strip()
    action = request.form.get('action', '').strip()
    if action not in ('award','revoke') or not member_id.isdecimal() or len(member_id)>20 or not achievement_id.isdecimal():
        abort(400)
    with connect() as db:
        member = db.execute('SELECT display_name FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone()
        achievement = db.execute('SELECT name FROM achievements WHERE id=? AND active=1',(achievement_id,)).fetchone()
        if member is None or achievement is None:
            flash('Member or achievement is no longer available. Refresh the page.', 'error')
            return redirect(url_for('home'))
        owned = db.execute('SELECT 1 FROM unlocks WHERE member_id=? AND achievement_id=?',(member_id,achievement_id)).fetchone() is not None
        queued = db.execute("SELECT 1 FROM award_queue WHERE member_id=? AND achievement_id=? AND action=? AND status='pending'",(member_id,achievement_id,action)).fetchone() is not None
        if queued or (owned if action=='award' else not owned):
            flash('No change queued: that achievement is already pending or not eligible for this action.', 'error')
            return redirect(url_for('home'))
        db.execute('INSERT INTO award_queue (achievement_id, member_id, action) VALUES (?, ?, ?)', (achievement_id, member_id, action))
    flash(f"{'Award' if action=='award' else 'Revoke'} queued: {achievement['name']} for {member['display_name']}.", 'success')
    return redirect(url_for('home'))

def _member_queue_state(db, member_id):
    owned = [r[0] for r in db.execute('SELECT achievement_id FROM unlocks WHERE member_id=?', (member_id,))]
    waiting = {'award': [], 'revoke': []}
    for row in db.execute("SELECT DISTINCT achievement_id,action FROM award_queue WHERE member_id=? AND status='pending'", (member_id,)):
        waiting.setdefault(row['action'], []).append(row['achievement_id'])
    return dict(owned=owned, waiting=waiting)

@app.get('/api/member-state/<member_id>')
def member_state(member_id):
    if not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:
        abort(400)
    with connect() as db:
        member = db.execute('SELECT display_name FROM member_directory WHERE member_id=? AND is_bot=0', (member_id,)).fetchone()
        if member is None:
            abort(404)
        return dict(member_id=member_id, name=member['display_name'], state=_member_queue_state(db, member_id))

@app.post('/api/member-actions')
def member_actions():
    if not request.is_json:
        return dict(error='Send a JSON action request.'), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return dict(error='Invalid action request.'), 400
    member_id = str(payload.get('member_id', ''))
    action = payload.get('action')
    raw_ids = payload.get('achievement_ids')
    if action not in ('award','revoke') or not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:
        return dict(error='Choose a valid member and action.'), 400
    if not isinstance(raw_ids,list) or not 1<=len(raw_ids)<=100:
        return dict(error='Select between 1 and 100 achievements.'), 400
    ids=[]
    for value in raw_ids:
        if isinstance(value,bool) or not isinstance(value,(str,int)) or not str(value).isascii() or not str(value).isdecimal():
            return dict(error='Invalid achievement selection.'), 400
        value=int(value)
        if not 1<=value<=9223372036854775807:
            return dict(error='Invalid achievement selection.'), 400
        if value not in ids: ids.append(value)
    queued=[];skipped=[]
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        member = db.execute('SELECT display_name FROM member_directory WHERE member_id=? AND is_bot=0', (member_id,)).fetchone()
        if member is None:
            return dict(error='Member is no longer synced. Refresh Main.'), 404
        current = _member_queue_state(db,member_id)
        owned=set(current['owned']);pending=set(current['waiting']['award']+current['waiting']['revoke'])
        for aid in ids:
            achievement=db.execute('SELECT name,active FROM achievements WHERE id=?',(aid,)).fetchone()
            reason=None
            if achievement is None: reason='Achievement no longer exists'
            elif action=='award' and not achievement['active']: reason='Archived award cannot be granted again'
            elif aid in pending: reason='An action is already queued'
            elif action=='award' and aid in owned: reason='Already unlocked'
            elif action=='revoke' and aid not in owned: reason='Not unlocked'
            name=achievement['name'] if achievement else 'Unavailable achievement'
            if reason:
                skipped.append(dict(id=aid,name=name,reason=reason));continue
            db.execute('INSERT INTO award_queue(achievement_id,member_id,action) VALUES(?,?,?)',(aid,member_id,action))
            queued.append(dict(id=aid,name=name))
        state=_member_queue_state(db,member_id)
    return dict(member_id=member_id,name=member['display_name'],action=action,queued=queued,skipped=skipped,state=state)

def parse_form():
    name = request.form.get('name','').strip()
    description = request.form.get('description','').strip()
    rarity = request.form.get('rarity', 'Common')
    icon = request.form.get('icon','🏆').strip() or '🏆'
    role_id = request.form.get('role_id','').strip()
    if not name or not description:
        raise ValueError('Name and description are required.')
    if len(name) > 80 or len(description) > 500 or len(icon) > 120:
        raise ValueError('A field is too long.')
    if rarity not in RARITIES:
        raise ValueError('Invalid rarity.')
    try:
        points = int(request.form.get('points','10'))
    except ValueError:
        raise ValueError('Points must be a whole number.')
    if not 0 <= points <= 10000:
        raise ValueError('Points must be between 0 and 10,000.')
    if role_id and (not role_id.isascii() or not role_id.isdecimal() or len(role_id) > 20):
        raise ValueError('Role ID must be numeric.')
    category=request.form.get('category','Uncategorized')
    if category not in CATEGORIES:raise ValueError('Invalid achievement category.')
    return (name, description, rarity, points, icon, role_id, int('beta_exclusive' in request.form), category)

@app.get('/achievements/catalog')
def achievement_catalog():
    from .security import can,current_access
    if not can(current_access(),'achievement_editor'):abort(403)
    with connect() as db:
        existing={r[0].casefold() for r in db.execute('SELECT name FROM achievements')}
    return render_template('achievement_catalog.html',catalog=CATALOG,categories=CATEGORIES,existing=existing)

@app.post('/achievements/catalog/<int:catalog_id>/add')
def add_catalog_achievement(catalog_id):
    from .security import can,current_access
    if not can(current_access(),'achievement_editor'):abort(403)
    if catalog_id<1 or catalog_id>len(CATALOG):abort(404)
    item=CATALOG[catalog_id-1]
    with connect() as db:
        if db.execute('SELECT 1 FROM achievements WHERE LOWER(name)=LOWER(?)',(item['name'],)).fetchone():
            flash('This achievement is already in the guild library.','error')
        else:
            db.execute('INSERT INTO achievements(name,description,rarity,points,icon,role_id,beta_exclusive,category) VALUES(?,?,?,?,?,?,?,?)',
                (item['name'],item['description'],item['rarity'],item['points'],item['icon'],'',0,item['category']))
            flash('Added to the guild achievement library. It has NOT been awarded to anyone.','success')
    return redirect(url_for('achievement_catalog'))

@app.route('/new', methods=['GET','POST'])
def new():
    if request.method == 'POST':
        try:
            values = parse_form()
            with connect() as db:
                db.execute('''INSERT INTO achievements
                    (name, description, rarity, points, icon, role_id, beta_exclusive, category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', values)
            flash('Achievement created!', 'success')
            return redirect(url_for('home'))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error), 'error')
    return render_template('form.html', item=None, rarities=RARITIES,categories=CATEGORIES)

@app.route('/edit/<int:achievement_id>', methods=['GET','POST'])
def edit(achievement_id):
    with connect() as db:
        item = db.execute('SELECT * FROM achievements WHERE id = ?', (achievement_id,)).fetchone()
    if item is None:
        abort(404)
    if request.method == 'POST':
        try:
            values = parse_form()
            with connect() as db:
                db.execute('''UPDATE achievements SET name=?, description=?, rarity=?,
                  points=?, icon=?, role_id=?, beta_exclusive=?, category=? WHERE id=?''', values + (achievement_id,))
            flash('Achievement updated!', 'success')
            return redirect(url_for('home'))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error), 'error')
    return render_template('form.html', item=item, rarities=RARITIES,categories=CATEGORIES)

@app.route('/achievements/<int:achievement_id>/delete', methods=['GET','POST'])
def delete_achievement(achievement_id):
    """Dangerous action, separately permissioned, CSRF-protected, confirmed by name."""
    with connect() as db:
        item=db.execute('SELECT * FROM achievements WHERE id=?',(achievement_id,)).fetchone()
        if item is None: abort(404)
        unlocked=db.execute('SELECT COUNT(*) FROM unlocks WHERE achievement_id=?',(achievement_id,)).fetchone()[0]
        queued=db.execute("SELECT COUNT(*) FROM award_queue WHERE achievement_id=? AND status='pending'",(achievement_id,)).fetchone()[0]
    if request.method=='POST':
        if request.form.get('confirm_name','').strip()!=item['name']:
            flash('Type the full achievement name to confirm deletion.','error')
            return redirect(url_for('delete_achievement',achievement_id=achievement_id))
        # Roles are external to the database. Prevent orphaning assigned reward roles.
        if item['role_id'] and unlocked:
            flash('Revoke this achievement from its members and wait for Discord to process those revocations before deletion.','error')
            return redirect(url_for('delete_achievement',achievement_id=achievement_id))
        from flask import g
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT name,role_id FROM achievements WHERE id=?',(achievement_id,)).fetchone()
            if current is None:abort(404)
            if current['role_id'] and db.execute('SELECT 1 FROM unlocks WHERE achievement_id=?',(achievement_id,)).fetchone():
                flash('Discord role awards still exist. Revoke them before deleting.','error')
                return redirect(url_for('delete_achievement',achievement_id=achievement_id))
            delete_achievement_records(db,[achievement_id])
            db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                (g.dashboard_access['discord_id'],str(achievement_id),'achievement_deleted',current['name']))
        flash('Achievement permanently deleted. Linked unlocks and queues were cleaned up.','success')
        return redirect(url_for('home'))
    return render_template('achievement_delete.html',item=item,unlocked=unlocked,queued=queued)


@app.post('/award')
def award():
    achievement_id = request.form.get('achievement_id', '').strip()
    member_id = request.form.get('member_id', '').strip().removeprefix('<@').removeprefix('!').removesuffix('>')
    if not achievement_id.isdecimal() or not member_id.isdecimal() or len(member_id) > 20:
        flash('Enter a valid achievement and numeric Discord Member ID.', 'error')
        return redirect(url_for('home'))
    with connect() as db:
        if db.execute('SELECT id FROM achievements WHERE id=? AND active=1', (achievement_id,)).fetchone() is None:
            flash('Achievement not found.', 'error')
        else:
            db.execute('INSERT INTO award_queue (achievement_id, member_id) VALUES (?, ?)', (achievement_id, member_id))
            flash('Award queued. Critbot will process it in a few seconds.', 'success')
    return redirect(url_for('home'))

@app.post('/revoke')
def revoke():
    achievement_id = request.form.get('achievement_id', '').strip()
    member_id = request.form.get('member_id', '').strip().removeprefix('<@').removeprefix('!').removesuffix('>')
    if not achievement_id.isdecimal() or not member_id.isdecimal() or len(member_id) > 20:
        flash('Enter a valid achievement and numeric Discord Member ID.', 'error')
        return redirect(url_for('home'))
    with connect() as db:
        if db.execute('SELECT id FROM achievements WHERE id=?', (achievement_id,)).fetchone() is None:
            flash('Achievement not found.', 'error')
        else:
            db.execute("INSERT INTO award_queue (achievement_id, member_id, action) VALUES (?, ?, 'revoke')", (achievement_id, member_id))
            flash('Revocation queued. Critbot will process it in a few seconds.', 'success')
    return redirect(url_for('home'))


def _awards_by_member():
    with connect() as db:
        rows = db.execute('''SELECT u.member_id, a.id, a.name, a.icon, a.rarity, a.points, u.awarded_at
                              FROM unlocks u JOIN achievements a ON a.id=u.achievement_id
                              ORDER BY a.name COLLATE NOCASE''').fetchall()
    result = {}
    for row in rows:
        result.setdefault(str(row['member_id']), []).append(dict(row))
    return result

def _valid_member_id(member_id):
    return bool(member_id and member_id.isascii() and member_id.isdecimal() and len(member_id)<=20)


def _staff(access):
    from .security import can
    return can(access,'member_staff')

def _welcomer(access):
    from .security import can
    return can(access,'member_notes')

def _profile_helper(access):
    from .security import can
    return can(access,'member_profile_edit')


def _profile_entry(db, member_id):
    row=db.execute('SELECT * FROM member_profiles WHERE member_id=?',(member_id,)).fetchone()
    return dict(row) if row else dict(profile_defaults(),member_id=member_id)


@app.get('/members')
def members_page():
    from .security import current_access
    access=current_access()
    with connect() as db:
        members=db.execute('''SELECT m.member_id,m.display_name,m.username,m.joined_at,
            COALESCE(p.main_character,'') AS main_character,COALESCE(p.main_class,'') AS main_class,
            COALESCE(p.interests,'') AS interests,
            COALESCE(p.tagline,'') AS tagline,COALESCE(p.banner,'flare') AS banner,
            COALESCE(p.theme,'ember') AS theme,COALESCE(p.portrait,'none') AS portrait,COALESCE(p.portrait_emblem,'none') AS portrait_emblem,COALESCE(p.goals,'') AS goals,COALESCE(p.guild_rank,'') AS guild_rank,
            COALESCE(p.about,'') AS about,COALESCE(p.availability,'') AS availability,
            COALESCE(p.featured_achievements,'[]') AS featured_achievements,
            (SELECT COUNT(*) FROM unlocks u WHERE u.member_id=m.member_id) AS award_count,
            (SELECT COUNT(*) FROM member_commendations c WHERE c.target_id=m.member_id) AS commendation_count
            FROM member_directory m LEFT JOIN member_profiles p ON p.member_id=m.member_id
            WHERE m.is_bot=0 ORDER BY m.display_name COLLATE NOCASE''').fetchall()
    roster=[]
    for r in members:
        item=dict(r)
        fields=['main_character','main_class','interests','goals','about','availability','tagline']
        item['filled']=sum(bool(item.get(k)) for k in fields)
        item['completion']=int(item['filled']*100/len(fields))
        item['portrait']=item['portrait'] if item['portrait'] in PORTRAITS else 'none'
        item['portrait_emblem']=item['portrait_emblem'] if item['portrait_emblem'] in EMBLEMS else 'none'
        item['personalized']=item['filled']>0 or item['banner']!='flare' or item['theme']!='ember' or item['portrait']!='none'
        item['palette_index']=sum(ord(c) for c in item['member_id'])%9
        item['banner']=item['banner'] if item['banner'] in BANNERS else 'flare'
        item['theme']=item['theme'] if item['theme'] in THEMES else 'ember'
        roster.append(item)
    return render_template('members.html',members=roster,access=access,portraits=PORTRAITS,emblems=EMBLEMS)



@app.get('/members/<member_id>')
def member_profile(member_id):
    from .security import current_access
    if not _valid_member_id(member_id):abort(404)
    access=current_access()
    with connect() as db:
        member=db.execute('SELECT * FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone()
        if member is None: abort(404)
        profile=_profile_entry(db,member_id)
        welcome=db.execute('SELECT * FROM member_welcome_notes WHERE member_id=?',(member_id,)).fetchone() if _welcomer(access) else None
        welcome_history=db.execute('SELECT * FROM member_welcome_history WHERE member_id=? ORDER BY id DESC LIMIT 15',(member_id,)).fetchall() if _welcomer(access) else []
        stats=member_stats(db,member_id)
        progress=member_progress(db,member_id,stats)
        collection=[dict(r) for r in db.execute('''SELECT a.id,a.name,a.icon,a.rarity,a.points,u.awarded_at
            FROM unlocks u JOIN achievements a ON a.id=u.achievement_id
            WHERE u.member_id=? ORDER BY u.awarded_at DESC,a.name COLLATE NOCASE''',(member_id,))]
        recent_days=[r[0] for r in db.execute('SELECT day FROM auto_active_days WHERE member_id=? ORDER BY day DESC LIMIT 14',(member_id,))]
        user_characters=member_owned_characters(db,member_id)
        commendations=commendation_summary(db,member_id)
        my_commendation=db.execute('SELECT trait FROM member_commendations WHERE author_id=? AND target_id=?',(access['discord_id'],member_id)).fetchone()
    staff=_staff(access)
    can_edit=bool(_profile_helper(access) or access['discord_id']==member_id)
    featured_ids,captions=read_showcase(profile,collection)
    featured=[dict(a,caption=captions.get(str(a['id']),'')) for a in collection if a['id'] in featured_ids]
    other_awards=[a for a in collection if a['id'] not in featured_ids]
    return render_template('member_profile.html',member=member,profile=profile,stats=stats,
        progress=progress,collection=collection,featured=featured,other_awards=other_awards,
        recent_days=recent_days,staff=staff,can_edit=can_edit,
        welcome=welcome,welcome_history=welcome_history,can_welcome=_welcomer(access),
        editing_self=access['discord_id']==member_id,portraits=PORTRAITS,emblems=EMBLEMS,
        characters=user_characters,commendations=commendations,commendation_traits=TRAITS,
        can_rank=access['level'] in ('owner','pope') or 'guild_rank_manage' in access['permissions'],ranks=RANKS,
        can_character_roles=access['level'] in ('owner','pope') or 'character_role_manage' in access['permissions'],class_roles=__import__('critbot.features.events.store',fromlist=['CLASS_ROLES']).CLASS_ROLES,
        my_commendation=my_commendation['trait'] if my_commendation else '')


def _bounded_field(name,limit):
    value=request.form.get(name,'').strip()
    if len(value)>limit:abort(400,description=f'{name} is too long')
    return value


@app.post('/members/<member_id>/profile')
def member_self_save(member_id):
    from .security import current_access
    if not _valid_member_id(member_id):abort(404)
    access=current_access()
    if not (access['discord_id']==member_id or _profile_helper(access)):abort(403)
    # Keep character names and classes in My Characters, not a second free-text editor.
    fields=('about','interests','availability','goals')
    values=[_bounded_field(k,n) for k,n in zip(fields,(800,240,240,240))]
    with connect() as db:
        if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone():abort(404)
        db.execute("""INSERT INTO member_profiles(member_id,about,interests,availability,goals)
            VALUES (?,?,?,?,?) ON CONFLICT(member_id) DO UPDATE SET
            about=excluded.about,interests=excluded.interests,
            availability=excluded.availability,goals=excluded.goals,updated_at=CURRENT_TIMESTAMP""",
            (member_id,*values))
    flash('Member profile saved.','success')
    return redirect(url_for('member_profile',member_id=member_id))


@app.get('/members/<member_id>/edit')
def member_profile_studio(member_id):
    from .security import current_access
    if not _valid_member_id(member_id):abort(404)
    access=current_access()
    if not (access['discord_id']==member_id or _profile_helper(access)):abort(403)
    with connect() as db:
        member=db.execute('SELECT * FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone()
        if member is None:abort(404)
        profile=_profile_entry(db,member_id)
        unlocked=[dict(a) for a in db.execute("SELECT a.id,a.name,a.icon,a.rarity,a.points FROM unlocks u JOIN achievements a ON a.id=u.achievement_id WHERE u.member_id=? ORDER BY a.name COLLATE NOCASE",(member_id,))]
    featured,captions=read_showcase(profile,unlocked)
    return render_template('member_profile_edit.html',member=member,profile=profile,
        unlocked=unlocked,featured=featured,captions=captions,themes=THEMES,studio_banners=STUDIO_BANNERS,studio_main_themes=STUDIO_MAIN_THEMES,studio_other_themes=STUDIO_OTHER_THEMES,
        banners=BANNERS,layouts=LAYOUTS,award_views=AWARD_VIEWS,frames=FRAMES,
        typography=TYPOGRAPHY,art_filters=ART_FILTERS,avatars=AVATARS,trophy_density=TROPHY_DENSITY,
        editing_self=access['discord_id']==member_id,portraits=PORTRAITS,emblems=EMBLEMS,portrait_groups=PORTRAIT_GROUPS,rank_styles=RANK_STYLES)


@app.post('/members/<member_id>/appearance')
def member_appearance_save(member_id):
    from .security import current_access
    if not _valid_member_id(member_id):abort(404)
    access=current_access()
    if not (access['discord_id']==member_id or _profile_helper(access)):abort(403)
    # Preserve existing user choices if an older client/form omits v1.01 fields.
    with connect() as db:
        existing=_profile_entry(db,member_id)
    defaults=profile_defaults()
    choices={name:request.form.get(name,existing.get(name,defaults.get(name,'')))
             for name in ('theme','banner','layout','award_view','frame_style','typography','art_filter','avatar_style','trophy_density')}
    enums={'theme':THEMES,'banner':BANNERS,'layout':LAYOUTS,'award_view':AWARD_VIEWS,'frame_style':FRAMES,
           'typography':TYPOGRAPHY,'art_filter':ART_FILTERS,'avatar_style':AVATARS,'trophy_density':TROPHY_DENSITY}
    if any(value not in enums[key] for key,value in choices.items()):abort(400)
    portrait=request.form.get('portrait',existing.get('portrait','none'))
    portrait_emblem=request.form.get('portrait_emblem',existing.get('portrait_emblem','none'))
    if portrait!='none' and portrait not in PORTRAITS:abort(400,description='Unknown portrait')
    if portrait_emblem not in EMBLEMS:abort(400,description='Unknown portrait emblem')
    rank_style=request.form.get('rank_style',existing.get('rank_style','banner'))
    if rank_style not in RANK_STYLES:abort(400)
    tagline=_bounded_field('tagline',100)
    showcase_caption=_bounded_field('showcase_caption',150)
    try:
        featured=[int(v) for v in request.form.getlist('featured')]
    except ValueError:abort(400)
    if len(featured)>3 or len(featured)!=len(set(featured)):abort(400)
    with connect() as db:
        if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone():abort(404)
        owned={r[0] for r in db.execute('SELECT achievement_id FROM unlocks WHERE member_id=?',(member_id,))}
        if any(aid not in owned for aid in featured):abort(400)
        captions={}
        for aid in featured:
            raw=request.form.get(f'caption_{aid}','').strip()
            if len(raw)>65:abort(400)
            if raw:captions[str(aid)]=raw
        db.execute("""INSERT INTO member_profiles(member_id,tagline,theme,banner,layout,award_view,
            frame_style,showcase_caption,featured_achievements,achievement_captions,
            typography,art_filter,avatar_style,trophy_density,portrait,portrait_emblem,rank_style)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(member_id) DO UPDATE SET
            tagline=excluded.tagline,theme=excluded.theme,banner=excluded.banner,layout=excluded.layout,
            award_view=excluded.award_view,frame_style=excluded.frame_style,
            showcase_caption=excluded.showcase_caption,
            featured_achievements=excluded.featured_achievements,
            achievement_captions=excluded.achievement_captions,
            typography=excluded.typography,art_filter=excluded.art_filter,
            avatar_style=excluded.avatar_style,trophy_density=excluded.trophy_density,
            portrait=excluded.portrait,portrait_emblem=excluded.portrait_emblem,rank_style=excluded.rank_style,
            updated_at=CURRENT_TIMESTAMP""",
            (member_id,tagline,choices['theme'],choices['banner'],choices['layout'],choices['award_view'],
             choices['frame_style'],showcase_caption,json.dumps(featured),json.dumps(captions),
             choices['typography'],choices['art_filter'],choices['avatar_style'],choices['trophy_density'],portrait,portrait_emblem,rank_style))
    flash('Profile appearance published. Your guild page has been updated.','success')
    return redirect(url_for('member_profile',member_id=member_id))


@app.post('/members/<member_id>/rank')
def member_rank_save(member_id):
    from .security import current_access
    if not _valid_member_id(member_id):abort(404)
    actor=current_access()
    if actor['level'] not in ('owner','pope') and 'guild_rank_manage' not in actor['permissions']:abort(403)
    new_rank=request.form.get('guild_rank','')
    if new_rank and new_rank not in RANKS:abort(400)
    # The council's top titles must never be assigned through ordinary officer access.
    if new_rank in ('Major Crit','Pope of Crit','Crit Lord') and actor['level'] not in ('owner','pope'):abort(403)
    with connect() as db:
        if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone():abort(404)
        current=db.execute('SELECT guild_rank FROM member_profiles WHERE member_id=?',(member_id,)).fetchone()
        previous=current['guild_rank'] if current else ''
        if previous in ('Major Crit','Pope of Crit','Crit Lord') and actor['level'] not in ('owner','pope'):abort(403)
        db.execute("""INSERT INTO member_profiles(member_id,guild_rank) VALUES(?,?)
             ON CONFLICT(member_id) DO UPDATE SET guild_rank=excluded.guild_rank,updated_at=CURRENT_TIMESTAMP""",(member_id,new_rank))
        db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                   (actor['discord_id'],member_id,'guild_rank_assigned',json.dumps({'previous':previous,'new':new_rank})))
    flash('Profile guild rank updated. This does not change their in-game rank.','success')
    return redirect(url_for('member_profile',member_id=member_id))


@app.post('/members/<member_id>/welcome')
def member_welcome_save(member_id):
    from .security import current_access
    if not _valid_member_id(member_id):abort(404)
    access=current_access()
    if not _welcomer(access):abort(403)
    status=request.form.get('welcome_status','Not contacted')
    if status not in ('Not contacted','Welcomed','Needs help','Follow-up','Settled in'):abort(400)
    note=_bounded_field('welcome_note',1000)
    if not note:abort(400,description='Add a short, useful note about the follow-up.')
    with connect() as db:
        if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone():abort(404)
        db.execute('''INSERT INTO member_welcome_notes(member_id,status,notes,updated_by)
          VALUES(?,?,?,?) ON CONFLICT(member_id) DO UPDATE SET
          status=excluded.status,notes=excluded.notes,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP''',
          (member_id,status,note,access['discord_id']))
        db.execute('INSERT INTO member_welcome_history(member_id,actor_id,status,note) VALUES(?,?,?,?)',
          (member_id,access['discord_id'],status,note))
        db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
          (access['discord_id'],member_id,'welcome_note_updated',status))
    flash('Member welcome note saved. Only people with New-member Notes access can see it.','success')
    return redirect(url_for('member_profile',member_id=member_id))


@app.post('/members/<member_id>/officer')
def member_staff_save(member_id):
    from .security import current_access
    if not _valid_member_id(member_id):abort(404)
    access=current_access()
    if not _staff(access):abort(403)
    status=request.form.get('staff_status','No designation')
    if status not in ('No designation','New member','Good standing','Follow-up','Inactive'):abort(400)
    department=_bounded_field('staff_department',80)
    notes=_bounded_field('staff_notes',2000)
    with connect() as db:
        if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone():abort(404)
        db.execute('''INSERT INTO member_profiles(member_id,staff_status,staff_department,staff_notes,staff_updated_at)
            VALUES (?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(member_id) DO UPDATE SET
            staff_status=excluded.staff_status,staff_department=excluded.staff_department,
            staff_notes=excluded.staff_notes,staff_updated_at=CURRENT_TIMESTAMP''',
            (member_id,status,department,notes))
        db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
            (access['discord_id'],member_id,'member_staff_updated',status))
    flash('Private officer notes updated.','success')
    return redirect(url_for('member_profile',member_id=member_id))

@app.get('/bulk')
def bulk():
    with connect() as db:
        achievements = db.execute('SELECT id, name, rarity, icon, points FROM achievements WHERE active=1 ORDER BY name').fetchall()
        members = db.execute('SELECT * FROM member_directory WHERE is_bot=0 ORDER BY LOWER(display_name), member_id').fetchall()
        unlocks = db.execute('SELECT achievement_id, member_id FROM unlocks').fetchall()
        pending = db.execute("SELECT achievement_id, member_id, action FROM award_queue WHERE status='pending'").fetchall()
    return render_template('bulk.html', achievements=achievements, members=members,
        member_awards=_awards_by_member(),
        unlocked={str(x['achievement_id']) + ':' + x['member_id'] for x in unlocks},
        queued_award={str(x['achievement_id']) + ':' + x['member_id'] for x in pending if x['action']=='award'},
        queued_revoke={str(x['achievement_id']) + ':' + x['member_id'] for x in pending if x['action']=='revoke'})

@app.post('/bulk')
def bulk_submit():
    achievement_id = request.form.get('achievement_id', '').strip()
    action = request.form.get('action', 'award').strip()
    member_ids = list(dict.fromkeys(request.form.getlist('member_ids')))
    if action not in ('award', 'revoke'):
        abort(400)
    if not achievement_id.isdecimal() or not member_ids or len(member_ids) > 10000:
        flash('Choose an achievement and at least one member.', 'error')
        return redirect(url_for('bulk'))
    if any(not m.isdecimal() or len(m)>20 for m in member_ids):
        abort(400)
    with connect() as db:
        if db.execute("SELECT 1 FROM achievements WHERE id=? AND (active=1 OR ?='revoke')", (achievement_id,action)).fetchone() is None:
            abort(400)
        existing = {row[0] for row in db.execute('SELECT member_id FROM unlocks WHERE achievement_id=?', (achievement_id,))}
        queued = {row[0] for row in db.execute("SELECT member_id FROM award_queue WHERE achievement_id=? AND action=? AND status='pending'", (achievement_id, action))}
        registered = {row[0] for row in db.execute('SELECT member_id FROM member_directory WHERE is_bot=0')}
        eligible = [mid for mid in member_ids if mid in registered and mid not in queued and ((mid not in existing) if action=='award' else (mid in existing))]
        if not eligible:
            flash('No eligible members. They may already have (or lack) this achievement, or have a pending request.', 'error')
            return redirect(url_for('bulk'))
        batch_id = db.execute('INSERT INTO bulk_batches(achievement_id, action) VALUES (?, ?)', (achievement_id, action)).lastrowid
        db.executemany('INSERT INTO award_queue(achievement_id, member_id, action, silent, batch_id) VALUES (?, ?, ?, 1, ?)',
            [(achievement_id, mid, action, batch_id) for mid in eligible])
    verb = 'awards' if action=='award' else 'revocations'
    flash(f'Queued {len(eligible)} {verb}. Skipped {len(member_ids)-len(eligible)} ineligible or pending. Critbot will process the batch and post one summary.', 'success')
    return redirect(url_for('bulk'))

@app.route('/automatic', methods=['GET', 'POST'])
def automatic_page():
    if request.method == 'POST':
        try:
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                operation = request.form.get('operation')
                if operation == 'settings':
                    channels = list(dict.fromkeys(request.form.getlist('channels') + parse_manual_ids(request.form.get('channels_manual'))))
                    available = {r[0] for r in db.execute('SELECT channel_id FROM auto_channel_directory')}
                    voice_all = int('voice_all' in request.form)
                    voice_channels = [] if voice_all else list(dict.fromkeys(request.form.getlist('voice_channels') + parse_manual_ids(request.form.get('voice_channels_manual'))))
                    voice_available = {r[0] for r in db.execute('SELECT channel_id FROM auto_voice_directory')}
                    enabled = int('enabled' in request.form)
                    voice_enabled = int('voice_enabled' in request.form)
                    days_enabled = int('days_enabled' in request.form)
                    # Manual input remains valid when the bot's directory cache lags Discord.
                    # Selected stale items remain visible until the owner removes them.
                    if enabled and not channels:
                        raise ValueError('Choose at least one text channel before enabling message tracking.')
                    if voice_enabled and not (voice_all or voice_channels):
                        raise ValueError('Choose at least one voice channel before enabling voice tracking.')
                    if days_enabled and not (channels or voice_all or voice_channels):
                        raise ValueError('Choose a text or voice channel before enabling active days.')
                    db.execute('UPDATE auto_settings SET enabled=?,voice_enabled=?,days_enabled=?,voice_all=?,voice_revision=voice_revision+1 WHERE id=1',
                               (enabled,voice_enabled,days_enabled,voice_all))
                    db.execute('DELETE FROM auto_channels')
                    db.executemany('INSERT INTO auto_channels VALUES(?)', [(c,) for c in channels])
                    db.execute('DELETE FROM auto_voice_channels')
                    db.executemany('INSERT INTO auto_voice_channels VALUES(?)', [(c,) for c in voice_channels])
                elif operation == 'quick_rule':
                    # One guided step creates both the achievement and its activity goal.
                    # BEGIN IMMEDIATE above keeps this atomic; errors never leave an orphan.
                    kind=request.form.get('kind','messages')
                    if kind not in KINDS:
                        raise ValueError('Choose chat, voice or active days.')
                    try:
                        target=int(request.form.get('target','0'))
                    except (ValueError,TypeError):
                        raise ValueError('Enter a whole-number goal.')
                    if not 1<=target<=1000000:
                        raise ValueError('The goal must be between 1 and 1,000,000.')
                    mode=request.form.get('reward_mode','new')
                    if mode=='new':
                        name=request.form.get('achievement_name','').strip()
                        rarity=request.form.get('rarity','Uncommon')
                        try: points=int(request.form.get('points','10'))
                        except (ValueError,TypeError):raise ValueError('Achievement points must be a whole number.')
                        if not name or len(name)>80 or rarity not in RARITIES or not 0<=points<=10000:
                            raise ValueError('Enter a name (up to 80 characters), valid rarity and 0–10,000 points.')
                        unit={'messages':'counted messages','voice':'voice minutes','days':'active days'}[kind]
                        desc=f'Participate in {target:,} {unit} with Flick the Crit.'
                        icon={'messages':'💬','voice':'🎙️','days':'✨'}[kind]
                        try:
                            aid=db.execute("INSERT INTO achievements(name,description,rarity,points,icon,role_id,beta_exclusive) VALUES(?,?,?,?,?,'',0)",
                                (name,desc,rarity,points,icon)).lastrowid
                        except sqlite3.IntegrityError:
                            raise ValueError('An achievement with that name already exists. Choose a different name or select Existing achievement.')
                    elif mode=='existing':
                        try:aid=int(request.form.get('achievement_id','0'))
                        except (ValueError,TypeError):raise ValueError('Select an existing achievement.')
                        if not db.execute('SELECT 1 FROM achievements WHERE id=?',(aid,)).fetchone():
                            raise ValueError('Select an existing achievement.')
                    else:
                        raise ValueError('Choose a new or existing achievement.')
                    old=db.execute('SELECT kind,target FROM auto_rules WHERE achievement_id=?',(aid,)).fetchone()
                    if old and old['kind']!=kind:
                        raise ValueError('This achievement already has a different activity type. Edit its existing goal instead.')
                    # Update only descriptions we generated. Never overwrite text edited by a member of staff.
                    if old and mode=='existing':
                        unit={'messages':'counted messages','voice':'voice minutes','days':'active days'}[kind]
                        previous=f"Participate in {old['target']:,} {unit} with Flick the Crit."
                        refreshed=f'Participate in {target:,} {unit} with Flick the Crit.'
                        db.execute('UPDATE achievements SET description=? WHERE id=? AND description=?',
                                   (refreshed,aid,previous))
                    db.execute('INSERT INTO auto_rules(achievement_id,target,enabled,kind) VALUES(?,?,1,?) ON CONFLICT(achievement_id) DO UPDATE SET target=excluded.target,enabled=1', (aid,target,kind))
                elif operation == 'rule':
                    aid = int(request.form.get('achievement_id', '0'))
                    target = int(request.form.get('target', '0'))
                    if not 1 <= target <= 1000000:
                        raise ValueError('Target must be between 1 and 1,000,000.')
                    if not db.execute('SELECT 1 FROM achievements WHERE id=?', (aid,)).fetchone():
                        raise ValueError('Choose an existing achievement.')
                    kind = request.form.get('kind', 'messages')
                    if kind not in KINDS:
                        raise ValueError('Choose a valid milestone type.')
                    old = db.execute('SELECT kind FROM auto_rules WHERE achievement_id=?', (aid,)).fetchone()
                    if old and old[0] != kind:
                        raise ValueError('This achievement already uses a different milestone type. Choose a separate achievement.')
                    limit=rule_limit(db)
                    existing=db.execute('SELECT enabled FROM auto_rules WHERE achievement_id=?',(aid,)).fetchone()
                    if limit and (not existing or not existing[0]) and db.execute('SELECT COUNT(*) FROM auto_rules WHERE enabled=1').fetchone()[0]>=limit:raise ValueError('Free includes 3 active automatic rules. Premium unlocks unlimited rules.')
                    db.execute('INSERT INTO auto_rules(achievement_id,target,enabled,kind) VALUES(?,?,1,?) ON CONFLICT(achievement_id) DO UPDATE SET target=excluded.target,enabled=1', (aid, target, kind))
                elif operation == 'toggle':
                    aid = int(request.form.get('achievement_id', '0'))
                    limit=rule_limit(db)
                    existing=db.execute('SELECT enabled FROM auto_rules WHERE achievement_id=?',(aid,)).fetchone()
                    if limit and existing and not existing[0] and db.execute('SELECT COUNT(*) FROM auto_rules WHERE enabled=1').fetchone()[0]>=limit:raise ValueError('Free includes 3 active automatic rules. Disable a rule or upgrade.')
                    db.execute('UPDATE auto_rules SET enabled=1-enabled WHERE achievement_id=?', (aid,))
                else:
                    abort(400)
            flash('Automatic achievement settings saved.', 'success')
        except ValueError as error:
            flash(str(error), 'error')
        return redirect(url_for('automatic_page'))
    with connect() as db:
        settings = db.execute('SELECT * FROM auto_settings WHERE id=1').fetchone()
        enabled = settings['enabled']
        voice_channels = db.execute('SELECT * FROM auto_voice_directory ORDER BY name').fetchall()
        voice_selected = {r[0] for r in db.execute('SELECT channel_id FROM auto_voice_channels')}
        channels = db.execute('SELECT * FROM auto_channel_directory ORDER BY name').fetchall()
        selected = {r[0] for r in db.execute('SELECT channel_id FROM auto_channels')}
        manual_text = sorted(selected - {r['channel_id'] for r in channels})
        manual_voice = sorted(voice_selected - {r['channel_id'] for r in voice_channels})
        achievements = db.execute('SELECT id,name FROM achievements WHERE active=1 ORDER BY name').fetchall()
        current_limit=rule_limit(db)
        running_ids={row[0] for row in db.execute('SELECT achievement_id FROM auto_rules WHERE enabled=1 ORDER BY achievement_id LIMIT ?',(current_limit or -1,))}
        rules = db.execute('SELECT r.*,a.name FROM auto_rules r JOIN achievements a ON a.id=r.achievement_id ORDER BY r.target,a.name').fetchall()
        progress = db.execute("""WITH ids AS (
            SELECT member_id FROM auto_progress UNION SELECT member_id FROM auto_voice_progress
            UNION SELECT member_id FROM auto_active_days), days AS (
            SELECT member_id,COUNT(*) AS total FROM auto_active_days GROUP BY member_id)
            SELECT COALESCE(m.display_name,'Member no longer synced') AS display_name,
                COALESCE(p.count,0) AS count,CAST(COALESCE(v.seconds,0)/60 AS INTEGER) AS minutes,
                COALESCE(d.total,0) AS days FROM ids i
            LEFT JOIN member_directory m ON m.member_id=i.member_id
            LEFT JOIN auto_progress p ON p.member_id=i.member_id
            LEFT JOIN auto_voice_progress v ON v.member_id=i.member_id
            LEFT JOIN days d ON d.member_id=i.member_id
            ORDER BY days DESC,minutes DESC,count DESC LIMIT 100""").fetchall()
        deliveries = db.execute("SELECT a.name,COALESCE(m.display_name,'Member no longer synced') AS display_name,COALESCE(q.status,'Already owned') AS status,q.detail FROM auto_deliveries d JOIN achievements a ON a.id=d.achievement_id LEFT JOIN member_directory m ON m.member_id=d.member_id LEFT JOIN award_queue q ON q.id=d.queue_id ORDER BY d.created_at DESC LIMIT 30").fetchall()
    return render_template('automatic.html', enabled=enabled, channels=channels, selected=selected,
                           achievements=achievements, rules=rules, running_ids=running_ids, progress=progress, deliveries=deliveries,
                           voice_channels=voice_channels, voice_selected=voice_selected, settings=settings,
                           manual_text=manual_text, manual_voice=manual_voice)

@app.get('/stats')
def stats_page():
    with connect() as db:
        roster = guild_roster(db)
    totals = {key:sum(m[key] for m in roster) for key in ('messages','voice_seconds','days','points','unlocks')}
    return render_template('stats.html', roster=roster, totals=totals)

@app.get('/stats/member/<member_id>')
def stats_member(member_id):
    if not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:
        abort(400)
    with connect() as db:
        member=db.execute('SELECT display_name,username FROM member_directory WHERE member_id=? AND is_bot=0', (member_id,)).fetchone()
        if member is None:
            abort(404)
        stats=member_stats(db, member_id)
        progress=member_progress(db, member_id, stats)
        dates=[r[0] for r in db.execute('SELECT day FROM auto_active_days WHERE member_id=? ORDER BY day DESC LIMIT 14', (member_id,))]
        collection=[dict(r) for r in db.execute('SELECT a.name,a.icon,a.rarity,a.points,u.awarded_at FROM unlocks u JOIN achievements a ON a.id=u.achievement_id WHERE u.member_id=? ORDER BY u.awarded_at DESC,a.name COLLATE NOCASE',(member_id,))]
    return dict(member=dict(member),stats=stats,progress=progress,recent_days=dates,collection=collection)

@app.get('/leaderboards')
def leaderboards_page():
    metric = request.args.get('metric', 'points')
    if metric not in METRICS:
        abort(400)
    query = request.args.get('q', '').strip()[:100]
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        abort(400)
    with connect() as db:
        ranking = ranked_members(db, metric)
    filtered = [r for r in ranking if query.casefold() in (r['display_name']+' '+r['username']).casefold()]
    pages = max(1, (len(filtered)+29)//30)
    page = min(page,pages)
    return render_template('leaderboards.html', metric=metric, metrics=METRICS,
        leaders=ranking[:3], rows=filtered[(page-1)*30:page*30], total=len(ranking),
        filtered_total=len(filtered), page=page, pages=pages, query=query)

@app.get('/cards')
def cards_page():
    with connect() as db:
        achievements = db.execute('SELECT id,name,rarity FROM achievements WHERE active=1 ORDER BY name COLLATE NOCASE').fetchall()
        members = db.execute('SELECT member_id,display_name,username FROM member_directory WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE').fetchall()
    return render_template('cards.html', achievements=achievements, members=members, rarities=RARITIES)

@app.get('/cards/preview')
def card_preview():
    achievement_id = request.args.get('achievement', '')
    if not achievement_id.isascii() or not achievement_id.isdecimal():
        abort(400)
    member_id = request.args.get('member', '')
    rarity = request.args.get('rarity', '')
    if rarity and rarity not in RARITIES:
        abort(400)
    with connect() as db:
        achievement = db.execute('SELECT * FROM achievements WHERE id=?', (achievement_id,)).fetchone()
        if achievement is None:
            abort(404)
        name = 'Guild Member'
        if member_id:
            if not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:
                abort(400)
            member = db.execute('SELECT display_name FROM member_directory WHERE member_id=? AND is_bot=0', (member_id,)).fetchone()
            if member is None:
                abort(404)
            name = member['display_name']
    item = dict(achievement)
    if rarity: item['rarity'] = rarity
    with connect() as db:brand=branding(db)
    item=dict(item);item['_brand']=brand
    payload = render_unlock_card(item, name)
    return Response(payload, mimetype='image/png', headers={'Cache-Control':'no-store','Content-Disposition':'inline; filename=critbot_card_preview.png'})

app.register_blueprint(hub_blueprint(connect))
app.register_blueprint(characters_blueprint(connect))
app.register_blueprint(request_blueprint(connect))
app.register_blueprint(social_blueprint(connect))
app.register_blueprint(involvement_blueprint(connect))

@app.context_processor
def social_navigation_context():
    try:
        from flask import g
        user=g.dashboard_access['discord_id']
        with connect() as db:
            from .social import unread_count, inbox_rows
            from .hub import _preferences
            from .version import VERSION
            return dict(hub_unread=unread_count(db,user),hub_notice_preview=inbox_rows(db,user,4),member_settings=_preferences(db,user),critbot_version=release_metadata()['version'])
    except (AttributeError,KeyError,sqlite3.Error):
        from .version import VERSION
        return dict(hub_unread=0,hub_notice_preview=[],member_settings={'theme':'ember','density':'comfortable','hub_layout':'balanced','compact_sidebar':0},critbot_version=release_metadata()['version'])

app.register_blueprint(operations_blueprint(connect))
app.register_blueprint(event_blueprint(connect))
app.register_blueprint(suggestion_blueprint(connect))
app.register_blueprint(product_blueprint(connect))

if __name__ == '__main__':
    init_db()
    from .achievement_catalog import install_catalog
    with connect() as db:install_catalog(db)
    print('Open http://127.0.0.1:5000 in your browser')

    if commercial():
        from waitress import serve
        hosted=os.getenv('CRITBOT_HOSTED','0')=='1'
        app.config.update(SESSION_COOKIE_SECURE=hosted,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax')
        serve(app,host='0.0.0.0' if hosted else '127.0.0.1',port=int(os.getenv('PORT','5000')))
    else:app.run(host='127.0.0.1', port=5000, debug=False)
