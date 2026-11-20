"""Member-owned character directory; optional main/alt metadata.

Character details are self-reported, not Blizzard-verified. No independent accounts
or authorization are created for alts: they belong to one Discord member ID.
"""
import sqlite3, json
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from .features.events.store import CLASS_ROLES

PROFESSIONS = ('', 'Alchemy', 'Blacksmithing', 'Enchanting', 'Engineering',
               'Herbalism', 'Leatherworking', 'Mining', 'Skinning', 'Tailoring')
MAX_CHARACTERS = 30


def init_characters(db):
    db.execute('''CREATE TABLE IF NOT EXISTS member_characters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id TEXT NOT NULL,
        name TEXT NOT NULL,
        class_name TEXT NOT NULL,
        profession_one TEXT NOT NULL DEFAULT '',
        profession_two TEXT NOT NULL DEFAULT '',
        is_main INTEGER NOT NULL DEFAULT 0 CHECK(is_main IN (0,1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(member_id, name COLLATE NOCASE)
    )''')
    if 'roles_json' not in {r[1] for r in db.execute('PRAGMA table_info(member_characters)')}:
        db.execute("ALTER TABLE member_characters ADD COLUMN roles_json TEXT NOT NULL DEFAULT '[]'")
    # Existing characters get their class-compatible roles; preserve manually narrowed choices.
    for row in db.execute("SELECT id,class_name,roles_json FROM member_characters"):
        if row['roles_json']=='[]' and row['class_name'] in CLASS_ROLES:
            db.execute('UPDATE member_characters SET roles_json=? WHERE id=?',(json.dumps(list(CLASS_ROLES[row['class_name']])),row['id']))
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS ix_member_main_character
                  ON member_characters(member_id) WHERE is_main=1''')
    # Keep existing main characters when migrating from v1.01, without deleting alts.
    for row in db.execute("SELECT member_id,main_character,main_class FROM member_profiles WHERE TRIM(main_character)!=''").fetchall():
        if row['main_class'] not in CLASS_ROLES or not 2 <= len(row['main_character'].strip()) <= 40:
            continue
        member_id, name, cls = row['member_id'], row['main_character'].strip(), row['main_class']
        has_main = db.execute('SELECT 1 FROM member_characters WHERE member_id=? AND is_main=1', (member_id,)).fetchone()
        db.execute('''INSERT OR IGNORE INTO member_characters(member_id,name,class_name,is_main)
                      VALUES(?,?,?,?)''', (member_id, name, cls, 0 if has_main else 1))


def owned(db, member_id):
    rows=[dict(r) for r in db.execute('''SELECT * FROM member_characters WHERE member_id=?
             ORDER BY is_main DESC,name COLLATE NOCASE,id''', (str(member_id),))]
    for row in rows:
        try: row['roles']=valid_roles(row['class_name'],json.loads(row['roles_json']))
        except (ValueError,TypeError):row['roles']=list(CLASS_ROLES.get(row['class_name'],()))
    return rows


def valid_roles(cls, values):
    allowed=CLASS_ROLES.get(cls,())
    chosen=list(dict.fromkeys(values))
    if not chosen or any(r not in allowed for r in chosen):
        raise ValueError('Select at least one class-compatible role.')
    return chosen

def add(db, member_id, name, cls, p1='', p2='', make_main=False, roles=None):
    name = name.strip()
    if not 2 <= len(name) <= 40 or '\n' in name or '\r' in name or cls not in CLASS_ROLES:
        raise ValueError('Enter a character name (2–40 characters) and a valid class.')
    if p1 not in PROFESSIONS or p2 not in PROFESSIONS or (p1 and p1 == p2):
        raise ValueError('Choose up to two different professions.')
    roles=valid_roles(cls,roles if roles is not None else CLASS_ROLES[cls])
    mid = str(member_id)
    existing = db.execute('SELECT id,class_name FROM member_characters WHERE member_id=? AND name=? COLLATE NOCASE', (mid,name)).fetchone()
    if existing:
        if existing['class_name'] != cls:
            raise ValueError('That character is already saved with a different class. Remove it first to change class.')
        if make_main: choose_main(db,mid,existing['id'])
        return existing['id']
    if db.execute('SELECT COUNT(*) FROM member_characters WHERE member_id=?',(mid,)).fetchone()[0] >= MAX_CHARACTERS:
        raise ValueError('You have reached the character limit.')
    has_main = bool(db.execute('SELECT 1 FROM member_characters WHERE member_id=? AND is_main=1',(mid,)).fetchone())
    primary = (not has_main) or make_main
    if primary:
        db.execute('UPDATE member_characters SET is_main=0 WHERE member_id=?',(mid,))
    new_id = db.execute('''INSERT INTO member_characters(member_id,name,class_name,profession_one,profession_two,is_main,roles_json)
                     VALUES(?,?,?,?,?,?,?)''',(mid,name,cls,p1,p2,int(primary),json.dumps(roles))).lastrowid
    if primary:
        _sync_main(db,mid,name,cls)
    return new_id


def _sync_main(db, member_id, name, cls):
    db.execute('''INSERT INTO member_profiles(member_id,main_character,main_class)
        VALUES(?,?,?) ON CONFLICT(member_id) DO UPDATE SET
        main_character=excluded.main_character,main_class=excluded.main_class,
        updated_at=CURRENT_TIMESTAMP''',(member_id,name,cls))
    db.execute('''INSERT INTO member_hub_settings(member_id,character_name,character_class)
        VALUES(?,?,?) ON CONFLICT(member_id) DO UPDATE SET
        character_name=excluded.character_name,character_class=excluded.character_class,
        updated_at=CURRENT_TIMESTAMP''',(member_id,name,cls))


def choose_main(db, member_id, char_id):
    member_id = str(member_id)
    character = db.execute('SELECT * FROM member_characters WHERE id=? AND member_id=?',(char_id,member_id)).fetchone()
    if character is None: raise LookupError('Character not found on your account.')
    db.execute('UPDATE member_characters SET is_main=0 WHERE member_id=?',(member_id,))
    db.execute('UPDATE member_characters SET is_main=1 WHERE id=?',(char_id,))
    _sync_main(db,member_id,character['name'],character['class_name'])


def remove(db, member_id, char_id):
    member_id = str(member_id)
    char = db.execute('SELECT is_main FROM member_characters WHERE id=? AND member_id=?',(char_id,member_id)).fetchone()
    if not char: raise LookupError('Character not found on your account.')
    db.execute('DELETE FROM member_characters WHERE id=? AND member_id=?',(char_id,member_id))
    if char['is_main']:
        next_char = db.execute('SELECT * FROM member_characters WHERE member_id=? ORDER BY id LIMIT 1',(member_id,)).fetchone()
        if next_char:
            choose_main(db,member_id,next_char['id'])
        else:
            _sync_main(db,member_id,'','')


def blueprint(connect):
    bp=Blueprint('characters',__name__)

    @bp.get('/hub/characters')
    def home():
        me = g.dashboard_access['discord_id']
        with connect() as db: characters=owned(db,me)
        return render_template('hub_characters.html',characters=characters,classes=CLASS_ROLES,professions=PROFESSIONS)

    @bp.post('/hub/characters/new')
    def create():
        me = g.dashboard_access['discord_id']
        try:
            with connect() as db:
                add(db,me,request.form.get('name',''),request.form.get('class_name',''),
                    request.form.get('profession_one',''),request.form.get('profession_two',''),
                    request.form.get('is_main')=='1', request.form.getlist('roles'))
            flash('Character added to your account.','success')
        except (ValueError, sqlite3.IntegrityError) as exc:flash(str(exc),'error')
        return redirect(url_for('characters.home'))

    @bp.post('/hub/characters/<int:char_id>/main')
    def mark_main(char_id):
        with connect() as db:
            try: choose_main(db,g.dashboard_access['discord_id'],char_id)
            except LookupError:abort(404)
        flash('Main character updated.','success')
        return redirect(url_for('characters.home'))

    @bp.post('/hub/characters/<int:char_id>/delete')
    def delete(char_id):
        with connect() as db:
            try: remove(db,g.dashboard_access['discord_id'],char_id)
            except LookupError:abort(404)
        flash('Character removed. Existing dungeon rosters and completed orders keep their historical character names.','success')
        return redirect(url_for('characters.home'))

    @bp.post('/hub/characters/<int:char_id>/roles')
    def edit_roles(char_id):
        actor=g.dashboard_access; member_id=request.form.get('member_id',actor['discord_id']).strip()
        if member_id != actor['discord_id'] and not (actor['level'] in ('owner','pope') or 'character_role_manage' in actor['permissions']):abort(403)
        if not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:abort(400)
        with connect() as db:
            char=db.execute('SELECT class_name FROM member_characters WHERE id=? AND member_id=?',(char_id,member_id)).fetchone()
            if char is None:abort(404)
            try:roles=valid_roles(char['class_name'],request.form.getlist('roles'))
            except ValueError as exc:
                flash(str(exc),'error')
                return redirect(url_for('characters.home') if member_id==actor['discord_id'] else url_for('member_profile',member_id=member_id))
            db.execute('UPDATE member_characters SET roles_json=? WHERE id=? AND member_id=?',(json.dumps(roles),char_id,member_id))
            if member_id!=actor['discord_id']:
                db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                           (actor['discord_id'],member_id,'character_roles_updated',json.dumps({'character_id':char_id,'roles':roles})))
        flash('Character roles updated.','success')
        return redirect(url_for('characters.home') if member_id==actor['discord_id'] else url_for('member_profile',member_id=member_id))

    return bp
