import sqlite3
from pathlib import Path
from datetime import datetime
STATUSES=('open','planned','completed','declined')

def init_suggestions(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='guild_suggestions'").fetchone():
        source=db.execute('PRAGMA database_list').fetchone()[2]
        if source:
            folder=Path(source).parent
            if folder.name=='data':folder=folder.parent
            folder=folder/'backups';folder.mkdir(exist_ok=True)
            with sqlite3.connect(folder/('critbot_before_suggestions_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')) as target:db.backup(target)
    db.executescript('''CREATE TABLE IF NOT EXISTS suggestion_board(
      id INTEGER PRIMARY KEY CHECK(id=1),channel_id TEXT NOT NULL DEFAULT '',guild_id TEXT NOT NULL DEFAULT '',message_id TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'draft',last_error TEXT NOT NULL DEFAULT '');
      INSERT OR IGNORE INTO suggestion_board(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS guild_suggestions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,body TEXT NOT NULL,author_id TEXT NOT NULL,author_name TEXT NOT NULL,
        guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,message_id TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'open',
        staff_note TEXT NOT NULL DEFAULT '',publish_state TEXT NOT NULL DEFAULT 'queued',last_error TEXT NOT NULL DEFAULT '',
        revision INTEGER NOT NULL DEFAULT 1,synced_revision INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
      CREATE TABLE IF NOT EXISTS suggestion_board_retire(
        id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,
        message_id TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'queued',last_error TEXT NOT NULL DEFAULT '');
      CREATE TABLE IF NOT EXISTS suggestion_votes(suggestion_id INTEGER NOT NULL,member_id TEXT NOT NULL,direction INTEGER NOT NULL CHECK(direction IN (-1,1)),PRIMARY KEY(suggestion_id,member_id));''')
    board_cols={r[1] for r in db.execute('PRAGMA table_info(suggestion_board)')}
    if 'results_channel_id' not in board_cols:
        db.execute("ALTER TABLE suggestion_board ADD COLUMN results_channel_id TEXT NOT NULL DEFAULT ''")
        # Existing installs continue posting where they already did until the admin selects
        # a separate feed. This never moves or rewrites existing suggestion messages.
        db.execute("UPDATE suggestion_board SET results_channel_id=channel_id WHERE results_channel_id=''")
    if 'feed_needs_sync' not in board_cols:
        db.execute("ALTER TABLE suggestion_board ADD COLUMN feed_needs_sync INTEGER NOT NULL DEFAULT 0")
    cols={r[1] for r in db.execute('PRAGMA table_info(guild_suggestions)')}
    for name,decl in [('category',"TEXT NOT NULL DEFAULT 'General'"),('priority',"TEXT NOT NULL DEFAULT 'normal'"),
                      ('assigned_to',"TEXT NOT NULL DEFAULT ''"),('internal_note',"TEXT NOT NULL DEFAULT ''"),
                      ('archived',"INTEGER NOT NULL DEFAULT 0"),('archived_by',"TEXT NOT NULL DEFAULT ''"),
                      ('archived_at',"TEXT"),('delete_state',"TEXT NOT NULL DEFAULT ''"),
                      ('delete_requested_by',"TEXT NOT NULL DEFAULT ''")]:
        if name not in cols:db.execute(f'ALTER TABLE guild_suggestions ADD COLUMN {name} {decl}')

def submit(db,title,body,author_id,author_name,guild_id,channel_id,board_message):
    title=title.strip();body=body.strip()
    if not title or len(title)>80 or not body or len(body)>1500:raise ValueError('Use a title up to 80 characters and details up to 1,500 characters.')
    db.execute('BEGIN IMMEDIATE');board=db.execute('SELECT * FROM suggestion_board WHERE id=1').fetchone()
    if board['state']!='posted' or (board['guild_id'],board['channel_id'],board['message_id'])!=(str(guild_id),str(channel_id),str(board_message)):
        db.rollback();raise ValueError('This suggestion board is no longer active.')
    pending=db.execute("SELECT COUNT(*) FROM guild_suggestions WHERE author_id=? AND guild_id=? AND archived=0 AND delete_state='' AND publish_state IN ('queued','posting','uncertain')",(str(author_id),str(guild_id))).fetchone()[0]
    if pending>=3:db.rollback();raise ValueError('You have three suggestions waiting to post. Wait for Critbot to publish them first.')
    # The source channel is for the permanent submission button; the destination
    # channel belongs to the idea post and is frozen on each idea at submission time.
    # Fallback only serves old configurations until both channels are configured.
    feed_channel=board['results_channel_id'] or board['channel_id']
    sid=db.execute('INSERT INTO guild_suggestions(title,body,author_id,author_name,guild_id,channel_id) VALUES(?,?,?,?,?,?)',
        (title,body,str(author_id),author_name[:100],str(guild_id),str(feed_channel))).lastrowid
    db.commit();return sid

def vote(db,sid,member_id,direction,guild_id,channel_id,message_id):
    if direction not in (-1,1):raise ValueError('Invalid vote.')
    db.execute('BEGIN IMMEDIATE');item=db.execute('SELECT * FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
    if item is None or item['archived'] or item['delete_state'] or item['status']!='open' or item['publish_state']!='posted' or (item['guild_id'],item['channel_id'],item['message_id'])!=(str(guild_id),str(channel_id),str(message_id)):
        db.rollback();raise ValueError('Voting is closed or this suggestion post is no longer active.')
    previous=db.execute('SELECT direction FROM suggestion_votes WHERE suggestion_id=? AND member_id=?',(sid,str(member_id))).fetchone()
    if previous and previous[0]==direction:
        db.execute('DELETE FROM suggestion_votes WHERE suggestion_id=? AND member_id=?',(sid,str(member_id)));result='Vote removed.'
    else:
        db.execute('INSERT INTO suggestion_votes VALUES(?,?,?) ON CONFLICT(suggestion_id,member_id) DO UPDATE SET direction=excluded.direction',(sid,str(member_id),direction));result='Vote saved.'
    db.execute('UPDATE guild_suggestions SET revision=revision+1 WHERE id=?',(sid,));db.commit();return result

def totals(db,sid):
    values=dict(db.execute('SELECT direction,COUNT(*) FROM suggestion_votes WHERE suggestion_id=? GROUP BY direction',(sid,)).fetchall())
    return dict(support=values.get(1,0),oppose=values.get(-1,0),score=values.get(1,0)-values.get(-1,0))
