import os,time,sqlite3
from pathlib import Path
from datetime import datetime,timezone
PREMIUM_FEATURES={'cards','bulk','seasons','branding','exports'}

def commercial():return False  # Single-guild edition: subscriptions and licensing disabled
def guild_id():return os.getenv('CRITBOT_GUILD_ID','').strip()
def init_premium(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='premium_access'").fetchone():
        source=db.execute('PRAGMA database_list').fetchone()[2]
        if source:
            folder=Path(source).parent
            if folder.name=='data':folder=folder.parent
            folder=folder/'backups';folder.mkdir(exist_ok=True)
            with sqlite3.connect(folder/('critbot_before_premium_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')) as target:db.backup(target)
    db.executescript('''CREATE TABLE IF NOT EXISTS guild_branding(id INTEGER PRIMARY KEY CHECK(id=1),name TEXT NOT NULL DEFAULT 'FLICK THE CRIT',tagline TEXT NOT NULL DEFAULT 'THE CRIT IS A MYTH',accent TEXT NOT NULL DEFAULT '',theme TEXT NOT NULL DEFAULT 'crest');
    INSERT OR IGNORE INTO guild_branding(id) VALUES(1);
    CREATE TABLE IF NOT EXISTS guild_seasons(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,metric TEXT NOT NULL,starts REAL NOT NULL,ends REAL NOT NULL,closed INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS season_scores(season_id INTEGER NOT NULL,member_id TEXT NOT NULL,score REAL NOT NULL DEFAULT 0,PRIMARY KEY(season_id,member_id));
    CREATE TABLE IF NOT EXISTS premium_access(guild_id TEXT PRIMARY KEY,trial_until REAL NOT NULL DEFAULT 0,discord_until REAL NOT NULL DEFAULT 0,entitlement_id TEXT NOT NULL DEFAULT '',last_checked REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS premium_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);''')
def plan(db,now=None):
    return dict(premium=True,source='Flick the Crit guild edition',expires=None)

def rule_limit(db):return None

def allowed(db,feature):return True

def grant_trial(db,days):
    gid=guild_id()
    if not gid.isdecimal() or not 0<=days<=30:raise ValueError('Configure a server ID; trial duration must be 0–30 days.')
    until=time.time()+days*86400 if days else 0
    db.execute('INSERT INTO premium_access(guild_id,trial_until) VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET trial_until=excluded.trial_until',(gid,until))
    db.execute('INSERT INTO premium_audit(guild_id,action,detail) VALUES(?,?,?)',(gid,'trial',str(days)+' days'))
def save_entitlements(db,entries,sku,now=None):
    now=time.time() if now is None else now;gid=guild_id();active=[]
    for item in entries:
        end=getattr(item,'ends_at',None);start=getattr(item,'starts_at',None)
        if str(item.guild_id)!=gid or str(item.sku_id)!=str(sku) or item.deleted:continue
        if start and start.timestamp()>now:continue
        if end and end.timestamp()<=now:continue
        active.append((min(now+300,end.timestamp()) if end else now+300,str(item.id)))
    until,eid=max(active,default=(0,''))
    db.execute('INSERT INTO premium_access(guild_id,discord_until,entitlement_id,last_checked) VALUES(?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET discord_until=excluded.discord_until,entitlement_id=excluded.entitlement_id,last_checked=excluded.last_checked',(gid,until,eid,now))

def season_credit(db,member_id,metric,start,end,amount):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='guild_seasons'").fetchone() or not allowed(db,'seasons'):return
    for row in db.execute('SELECT * FROM guild_seasons WHERE metric=? AND closed=0 AND starts<=? AND ends>?',(metric,end,start)).fetchall():
        credit=amount if metric=='messages' and row['starts']<=end<row['ends'] else (max(0,min(end,row['ends'])-max(start,row['starts'])) if metric=='voice' else 0)
        if credit:db.execute('INSERT INTO season_scores VALUES(?,?,?) ON CONFLICT(season_id,member_id) DO UPDATE SET score=score+excluded.score',(row['id'],str(member_id),credit))
def branding(db):
    if not allowed(db,'branding'):return None
    return dict(db.execute('SELECT * FROM guild_branding WHERE id=1').fetchone())
