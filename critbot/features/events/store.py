import sqlite3,json
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ZONE=ZoneInfo('America/New_York')

def init_events(db):
    if 'kind' not in {r[1] for r in db.execute('PRAGMA table_info(guild_events)')}:
        source=db.execute('PRAGMA database_list').fetchone()[2]
        if source:
            folder=Path(source).parent
            if folder.name=='data':folder=folder.parent
            folder=folder/'backups';folder.mkdir(exist_ok=True)
            backup=folder/('critbot_before_lfg_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
            with sqlite3.connect(backup) as target:db.backup(target)
    db.executescript('''BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS guild_events(
          id INTEGER PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,
          starts_at TEXT NOT NULL,location TEXT NOT NULL,channel_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft',guild_id TEXT NOT NULL DEFAULT '',message_id TEXT NOT NULL DEFAULT '',
          revision INTEGER NOT NULL DEFAULT 1,synced_revision INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS guild_event_members(
          event_id INTEGER NOT NULL,member_id TEXT NOT NULL,name TEXT NOT NULL,
          rsvp TEXT NOT NULL DEFAULT 'none',attended INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(event_id,member_id));
        ''')
    for table,name,declaration in [('guild_events','kind',"TEXT NOT NULL DEFAULT 'general'"),('guild_events','config_json',"TEXT NOT NULL DEFAULT '{}'"),('guild_event_members','choice',"TEXT NOT NULL DEFAULT ''"),('guild_event_members','class_name',"TEXT NOT NULL DEFAULT ''")]:
        if name not in {r[1] for r in db.execute('PRAGMA table_info('+table+')')}:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
    # Rev3: dungeons are active quick-fill LFG messages, never scheduled events.
    for name, decl in (
        ('scheduled_event_id', "TEXT NOT NULL DEFAULT ''"),
        ('scheduled_synced_revision', 'INTEGER NOT NULL DEFAULT 0'),
        ('scheduled_retry_at', "TEXT NOT NULL DEFAULT ''"),
        ('scheduled_error', "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in {r[1] for r in db.execute('PRAGMA table_info(guild_events)')}:
            db.execute(f'ALTER TABLE guild_events ADD COLUMN {name} {decl}')
    db.commit()

def parse_event(form):
    title=form.get('title','').strip();description=form.get('description','').strip();location=form.get('location','').strip()
    if not title or len(title)>80 or len(description)>1500 or len(location)>120:
        raise ValueError('Use a title up to 80 characters, description up to 1,500 and location up to 120.')
    if form.get('kind')=='dungeon':return title,description,datetime.now(timezone.utc).isoformat(),location
    try:
        local=datetime.fromisoformat(form.get('starts_at',''))
        if local.tzinfo is not None:raise ValueError()
        aware=local.replace(tzinfo=ZONE)
        if aware.astimezone(timezone.utc).astimezone(ZONE).replace(tzinfo=None)!=local:
            raise ValueError()
        if aware.utcoffset()!=local.replace(tzinfo=ZONE,fold=1).utcoffset():
            raise ValueError()
    except (ValueError,TypeError):raise ValueError('Choose a valid Eastern date/time. Avoid the skipped or repeated hour at daylight-saving changes.')
    return title,description,aware.astimezone(timezone.utc).isoformat(),location

def describe(event):
    result=dict(event);date=datetime.fromisoformat(result['starts_at']).astimezone(ZONE)
    result['local_time']='Live dungeon group' if result['kind']=='dungeon' else date.strftime('%b %d, %Y · %I:%M %p %Z')
    result['config']=json.loads(result['config_json'])
    result['kind_label']={'general':'Guild event','dungeon':'Dungeon LFG · no schedule','raid':'Raid','custom':'Custom event'}[result['kind']]
    result['input_time']=date.strftime('%Y-%m-%dT%H:%M');result['timestamp']=int(date.timestamp())
    return result

def participants(db,event_id):
    return [dict(r) for r in db.execute('SELECT * FROM guild_event_members WHERE event_id=? ORDER BY name COLLATE NOCASE',(event_id,))]

def rsvp(db,event_id,member_id,name,choice,guild_id,channel_id,message_id):
    if choice not in ('going','maybe','declined'):raise ValueError('Invalid RSVP.')
    db.execute('BEGIN IMMEDIATE')
    event=db.execute('SELECT * FROM guild_events WHERE id=?',(event_id,)).fetchone()
    if event is None or event['status']!='posted' or event['kind']!='general' or (event['guild_id'],event['channel_id'],event['message_id'])!=(str(guild_id),str(channel_id),str(message_id)):
        db.rollback();raise ValueError('This event is closed or the RSVP message is no longer active.')
    db.execute('''INSERT INTO guild_event_members(event_id,member_id,name,rsvp) VALUES(?,?,?,?)
        ON CONFLICT(event_id,member_id) DO UPDATE SET name=excluded.name,rsvp=excluded.rsvp,updated_at=CURRENT_TIMESTAMP''',(event_id,str(member_id),name[:100],choice))
    db.execute('UPDATE guild_events SET revision=revision+1 WHERE id=?',(event_id,));db.commit()


CLASSES = 'Warrior, Paladin, Hunter, Rogue, Priest, Shaman, Mage, Warlock, Druid'
DEFAULT_SLOTS = {'general':'','dungeon':'Tank | 1\nHealer | 1\nDPS | 3','raid':'Tank | 2\nHealer | 4\nDPS | 14','custom':' | 1'}
# WoW Forever (Classic-style) dungeon/raid roles; not every class may choose every role.
CLASS_ROLES = {
    'Warrior': ('Tank','DPS'), 'Paladin': ('Tank','Healer','DPS'),
    'Hunter': ('DPS',), 'Rogue': ('DPS',),
    'Priest': ('Healer','DPS'), 'Shaman': ('Healer','DPS'),
    'Mage': ('DPS',), 'Warlock': ('DPS',), 'Druid': ('Tank','Healer','DPS'),
}

def validate_role_class(kind, role, cls):
    if kind not in ('dungeon','raid'):
        return
    if cls not in CLASS_ROLES or role not in CLASS_ROLES[cls]:
        raise ValueError(f'{cls or "That class"} cannot join as {role or "that role"}. Choose a compatible class and role.')


def make_dungeon_post(db, *, title, leader_id, leader_toon, cls, role, channel_id, description=''):
    '''Shared creation path; publication happens only through Discord worker.

    No calendar date and no native Discord scheduled-event ID is ever generated.
    '''
    title=title.strip();leader_toon=leader_toon.strip();description=description.strip()
    validate_role_class('dungeon',role,cls)
    if not 2<=len(title)<=80 or not 2<=len(leader_toon)<=40 or len(description)>900:
        raise ValueError('Choose a dungeon (2–80 letters), character name (2–40), and notes under 900 characters.')
    if not str(leader_id).isdigit() or not str(channel_id).isdigit():
        raise ValueError('Invalid Discord member or channel.')
    cfg={'slots':[{'key':'slot0','name':'Tank','capacity':1}, {'key':'slot1','name':'Healer','capacity':1}, {'key':'slot2','name':'DPS','capacity':3}],
         'classes':list(CLASS_ROLES),'require_class':True,'leader_id':str(leader_id),'leader_name':leader_toon}
    role_slot={'Tank':'slot0','Healer':'slot1','DPS':'slot2'}[role]
    event_id=db.execute('''INSERT INTO guild_events(title,description,starts_at,location,channel_id,kind,config_json,status)
        VALUES(?,?,?,?,?,'dungeon',?,'queued')''',
        (title,description,datetime.now(timezone.utc).isoformat(),'',str(channel_id),json.dumps(cfg))).lastrowid
    db.execute('''INSERT INTO guild_event_members(event_id,member_id,name,rsvp,choice,class_name)
        VALUES(?,?,?,'going',?,?)''',(event_id,str(leader_id),leader_toon,role_slot,cls))
    return event_id


def parse_config(form):
    kind=form.get('kind','general')
    if kind not in DEFAULT_SLOTS:raise ValueError('Choose a valid group type.')
    if kind=='general':return kind,'{}'
    rows=[];names=set()
    for line in form.get('slots','').strip().splitlines():
        if not line.strip():continue
        parts=line.rsplit('|',1)
        if len(parts)!=2:raise ValueError('Use one option per line: Name | capacity.')
        name=parts[0].strip()
        try:capacity=int(parts[1].strip())
        except ValueError:raise ValueError('Capacity must be a whole number.')
        if not name or len(name)>40 or name.casefold() in names or not 0<=capacity<=100 or (kind in ('dungeon','raid') and capacity==0):
            raise ValueError('Use unique option names up to 40 characters and capacities 1–100 (custom groups may use 0 for unlimited).')
        names.add(name.casefold());rows.append(dict(key='slot'+str(len(rows)),name=name,capacity=capacity))
    if not 1<=len(rows)<=10:raise ValueError('Create between 1 and 10 signup options.')
    require_class=kind in ('dungeon','raid') or 'require_class' in form
    classes=[]
    if require_class:
        for value in form.get('classes',CLASSES).split(','):
            value=value.strip()
            if value and value.casefold() not in {c.casefold() for c in classes}:classes.append(value)
        if not 1<=len(classes)<=25 or any(len(c)>40 for c in classes):raise ValueError('Use 1–25 class choices, up to 40 characters each.')
        if kind in ('dungeon','raid'):
            if any(c not in CLASS_ROLES for c in classes):raise ValueError('Raids and dungeons must use supported WoW Forever classes.')
            if any(slot['name'] not in ('Tank','Healer','DPS') for slot in rows):raise ValueError('Raids and dungeons use Tank, Healer or DPS slots.')
    return kind,json.dumps(dict(slots=rows,require_class=require_class,classes=classes))

def signup(db,event_id,member_id,name,choice,class_name,guild_id,channel_id,message_id):
    db.execute('BEGIN IMMEDIATE')
    event=db.execute('SELECT * FROM guild_events WHERE id=?',(event_id,)).fetchone()
    if event is None or event['status']!='posted' or event['kind']=='general' or (event['guild_id'],event['channel_id'],event['message_id'])!=(str(guild_id),str(channel_id),str(message_id)):
        db.rollback();raise ValueError('This group is closed or its message is no longer active.')
    config=json.loads(event['config_json'])
    if choice is None:
        db.execute("UPDATE guild_event_members SET rsvp='declined',choice='',class_name='',updated_at=CURRENT_TIMESTAMP WHERE event_id=? AND member_id=?",(event_id,str(member_id)))
    else:
        option=next((o for o in config['slots'] if o['key']==choice),None)
        if option is None:db.rollback();raise ValueError('That signup option no longer exists.')
        if config['require_class'] and class_name not in config['classes']:db.rollback();raise ValueError('Choose a valid class.')
        if not name or not 2 <= len(name.strip()) <= 40:db.rollback();raise ValueError('Enter your character name (2–40 characters).')
        if event['kind'] in ('dungeon','raid'):
            try:validate_role_class(event['kind'],option['name'],class_name)
            except ValueError:
                db.rollback()
                raise
        used=db.execute("SELECT COUNT(*) FROM guild_event_members WHERE event_id=? AND choice=? AND rsvp='going' AND member_id!=?",(event_id,choice,str(member_id))).fetchone()[0]
        if option['capacity'] and used>=option['capacity']:db.rollback();raise ValueError('That option is full. Your existing signup was kept; choose another option.')
        db.execute("""INSERT INTO guild_event_members(event_id,member_id,name,rsvp,choice,class_name) VALUES(?,?,?,'going',?,?)
          ON CONFLICT(event_id,member_id) DO UPDATE SET name=excluded.name,rsvp='going',choice=excluded.choice,class_name=excluded.class_name,updated_at=CURRENT_TIMESTAMP""",(event_id,str(member_id),name[:100],choice,class_name if config['require_class'] else ''))
    db.execute('UPDATE guild_events SET revision=revision+1 WHERE id=?',(event_id,));db.commit()
