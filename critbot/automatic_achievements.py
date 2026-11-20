"""Persistent activity milestones. Rewards use Critbot's existing queue."""
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

GUILD_TIMEZONE = 'America/New_York'
KINDS = ('messages', 'voice', 'days')


def init_schema(db):
    if 'voice_all' not in {r[1] for r in db.execute('PRAGMA table_info(auto_settings)')}:
        source = db.execute('PRAGMA database_list').fetchone()[2]
        if source:
            backup_folder = Path(source).parent / 'backups'
            backup_folder.mkdir(exist_ok=True)
            backup = backup_folder / ('critbot_before_automatic_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db')
            with sqlite3.connect(backup) as destination:
                db.backup(destination)
    db.executescript('''
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS auto_settings (
            id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0);
        INSERT OR IGNORE INTO auto_settings(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS auto_channels (channel_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS auto_channel_directory (
            channel_id TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auto_rules (
            achievement_id INTEGER PRIMARY KEY, target INTEGER NOT NULL CHECK(target>0),
            enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS auto_progress (
            member_id TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0,
            last_counted REAL NOT NULL DEFAULT 0, last_message_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auto_deliveries (
            achievement_id INTEGER NOT NULL, member_id TEXT NOT NULL,
            queue_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(achievement_id, member_id));
        CREATE TABLE IF NOT EXISTS auto_voice_channels (channel_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS auto_voice_directory (channel_id TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auto_voice_progress (member_id TEXT PRIMARY KEY, seconds REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS auto_active_days (
            member_id TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY(member_id,day));
        CREATE TABLE IF NOT EXISTS auto_voice_days (
            member_id TEXT NOT NULL, day TEXT NOT NULL, seconds REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(member_id,day));
    ''')
    columns = {r[1] for r in db.execute('PRAGMA table_info(auto_settings)')}
    for name in ('voice_enabled', 'days_enabled'):
        if name not in columns:
            db.execute(f'ALTER TABLE auto_settings ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
    if 'voice_revision' not in columns:
        db.execute('ALTER TABLE auto_settings ADD COLUMN voice_revision INTEGER NOT NULL DEFAULT 0')
    if 'voice_all' not in columns:
        db.execute('ALTER TABLE auto_settings ADD COLUMN voice_all INTEGER NOT NULL DEFAULT 1')
    if 'kind' not in {r[1] for r in db.execute('PRAGMA table_info(auto_rules)')}:
        db.execute("ALTER TABLE auto_rules ADD COLUMN kind TEXT NOT NULL DEFAULT 'messages'")
    db.commit()


def queue_milestones(db, member_id, kind, progress):
    from .features.premium.store import allowed
    from .features.premium.store import rule_limit
    limit=rule_limit(db)
    rules = db.execute('''SELECT r.achievement_id,r.target FROM auto_rules r
        JOIN achievements a ON a.id=r.achievement_id WHERE r.enabled=1 AND r.kind=? AND (? IS NULL OR r.achievement_id IN (SELECT achievement_id FROM auto_rules WHERE enabled=1 ORDER BY achievement_id LIMIT ?))''', (kind,limit,limit or -1)).fetchall()
    for achievement_id, target in rules:
        if progress + 0.000001 < target * (60 if kind == 'voice' else 1):
            continue
        if db.execute('SELECT 1 FROM auto_deliveries WHERE achievement_id=? AND member_id=?',
                      (achievement_id, member_id)).fetchone():
            continue
        owned = db.execute('SELECT 1 FROM unlocks WHERE achievement_id=? AND member_id=?',
                           (achievement_id, member_id)).fetchone()
        pending = db.execute("SELECT id FROM award_queue WHERE achievement_id=? AND member_id=? AND status='pending' ORDER BY id LIMIT 1",
                             (achievement_id, member_id)).fetchone()
        queue_id = pending[0] if pending else None
        # Never undo a pending staff revoke or reissue a consumed milestone.
        if not owned and not pending:
            queue_id = db.execute("INSERT INTO award_queue(achievement_id,member_id,action) VALUES(?,?,'award')",
                                  (achievement_id, member_id)).lastrowid
        db.execute('INSERT INTO auto_deliveries(achievement_id,member_id,queue_id) VALUES(?,?,?)',
                   (achievement_id, member_id, queue_id))


def active_day(db, member_id, day):
    db.execute('INSERT OR IGNORE INTO auto_active_days VALUES(?,?)', (member_id, day))
    total = db.execute('SELECT COUNT(*) FROM auto_active_days WHERE member_id=?', (member_id,)).fetchone()[0]
    queue_milestones(db, member_id, 'days', total)


def record_message(db, member_id, channel_id, message_id, now=None):
    now = time.time() if now is None else now
    member_id, channel_id, message_id = map(str, (member_id, channel_id, message_id))
    db.execute('BEGIN IMMEDIATE')
    try:
        settings = db.execute('SELECT enabled,days_enabled FROM auto_settings WHERE id=1').fetchone()
        if not settings or not any(settings) or not db.execute(
                'SELECT 1 FROM auto_channels WHERE channel_id=?', (channel_id,)).fetchone():
            db.commit()
            return False
        if settings[1]:
            active_day(db, member_id, datetime.fromtimestamp(now, ZoneInfo(GUILD_TIMEZONE)).date().isoformat())
        if not settings[0]:
            db.commit()
            return False
        old = db.execute('SELECT count,last_counted,last_message_id FROM auto_progress WHERE member_id=?',
                         (member_id,)).fetchone()
        if old and (int(message_id) <= int(old[2]) or now - old[1] < 60):
            db.commit()
            return False
        count = (old[0] if old else 0) + 1
        db.execute('''INSERT INTO auto_progress VALUES(?,?,?,?) ON CONFLICT(member_id)
            DO UPDATE SET count=excluded.count,last_counted=excluded.last_counted,
            last_message_id=excluded.last_message_id''', (member_id, count, now, message_id))
        from .features.premium.store import season_credit
        season_credit(db,member_id,'messages',now,now,1)
        queue_milestones(db, member_id, 'messages', count)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def split_days(start, end):
    """Split real elapsed seconds at Eastern calendar boundaries, including DST."""
    zone = ZoneInfo(GUILD_TIMEZONE)
    while start < end:
        local = datetime.fromtimestamp(start, zone)
        midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), zone).timestamp()
        stop = min(end, midnight)
        yield local.date().isoformat(), stop - start
        start = stop


def voice_config(db):
    row = db.execute('SELECT voice_enabled,days_enabled,voice_revision,voice_all FROM auto_settings WHERE id=1').fetchone()
    channels = frozenset({'*'}) if row[3] else frozenset(r[0] for r in db.execute('SELECT channel_id FROM auto_voice_channels'))
    return (bool(row[0]), bool(row[1]), channels, row[2])


def record_voice(db, members, seconds, end, expected_config):
    """One live interval, from one in-process tracker. Never backfills offline time."""
    if seconds <= 0 or seconds > 30:
        return
    db.execute('BEGIN IMMEDIATE')
    try:
        config = voice_config(db)
        if config != expected_config or not (config[0] or config[1]):
            db.commit()
            return
        for member_id in members:
            member_id = str(member_id)
            if config[0]:
                db.execute('''INSERT INTO auto_voice_progress VALUES(?,?) ON CONFLICT(member_id)
                    DO UPDATE SET seconds=seconds+excluded.seconds''', (member_id, seconds))
                total = db.execute('SELECT seconds FROM auto_voice_progress WHERE member_id=?', (member_id,)).fetchone()[0]
                from .features.premium.store import season_credit
                season_credit(db,member_id,'voice',end-seconds,end,seconds)
                queue_milestones(db, member_id, 'voice', total)
            if config[1]:
                for day, amount in split_days(end - seconds, end):
                    db.execute('''INSERT INTO auto_voice_days VALUES(?,?,?) ON CONFLICT(member_id,day)
                        DO UPDATE SET seconds=seconds+excluded.seconds''', (member_id, day, amount))
                    total = db.execute('SELECT seconds FROM auto_voice_days WHERE member_id=? AND day=?', (member_id, day)).fetchone()[0]
                    if total + 0.000001 >= 60:
                        active_day(db, member_id, day)
        db.commit()
    except Exception:
        db.rollback()
        raise


def eligible_voice_members(guild, channels):
    """Two humans present; deafened users do not earn time. Muted users may listen."""
    eligible = set()
    for channel in guild.voice_channels:
        if ('*' not in channels and str(channel.id) not in channels) or channel == guild.afk_channel:
            continue
        if guild.me is None or not channel.permissions_for(guild.me).view_channel:
            continue
        humans = [m for m in channel.members if not m.bot and m.voice is not None]
        if len(humans) < 2:
            continue
        eligible.update(str(m.id) for m in humans if not m.voice.afk and not m.voice.deaf and not m.voice.self_deaf)
    return eligible


class VoiceTracker:
    """Live-only monotonic timing, with fresh baselines after reconnect/config changes."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.last = None
        self.members = set()
        self.config = None

    def sample(self, db, guild, monotonic_now, wall_now):
        config = voice_config(db)
        if self.last is not None and self.config == config:
            record_voice(db, self.members, monotonic_now - self.last, wall_now, config)
        self.members = eligible_voice_members(guild, config[2]) if (config[0] or config[1]) else set()
        self.last = monotonic_now
        self.config = config
