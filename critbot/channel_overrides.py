"""Validated manual channel routing and reactive bot-owned Discord directory sync.

Manual IDs are accepted only as numeric Discord snowflakes. The BOT must still have
access to the channel; publishing workers enforce guild ownership and Discord perms.
"""
import re

SNOWFLAKE = re.compile(r"^[0-9]{17,22}$")


def channel_id(value):
    value = str(value or '').strip()
    if not SNOWFLAKE.fullmatch(value) or int(value) == 0:
        raise ValueError('Enter a valid Discord channel ID (17–22 digits). Enable Developer Mode in Discord to copy it.')
    return value


def selected_channel(form, name='channel_id', manual_name=None):
    manual = str(form.get(manual_name or name + '_manual', '') or '').strip()
    selected = str(form.get(name, '') or '').strip()
    return channel_id(manual or selected)


def parse_manual_ids(value, limit=20):
    parts = [s.strip() for s in str(value or '').replace(',', '\n').splitlines() if s.strip()]
    if len(parts) > limit:
        raise ValueError('Enter at most 20 manual channel IDs.')
    return list(dict.fromkeys(channel_id(x) for x in parts))


def init_channel_sync(db):
    db.execute("""CREATE TABLE IF NOT EXISTS channel_sync_requests (
        id INTEGER PRIMARY KEY CHECK (id=1), requested_at TEXT NOT NULL DEFAULT '',
        completed_at TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'idle',
        detail TEXT NOT NULL DEFAULT '')""")
    db.execute("INSERT OR IGNORE INTO channel_sync_requests(id) VALUES (1)")
    db.execute("""CREATE TABLE IF NOT EXISTS channel_route_overrides (
        id INTEGER PRIMARY KEY CHECK(id=1), announcement_id TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("INSERT OR IGNORE INTO channel_route_overrides(id) VALUES (1)")
