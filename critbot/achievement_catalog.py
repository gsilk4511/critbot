"""Guild achievement library: 30 exact Dungeon Ledger awards + 18 CritBot originals.

Existing achievements are archived on the first migration, never erased. Existing unlocks,
Discord role IDs, and member histories remain untouched. Catalog installation is idempotent.
"""
import json
import re
from pathlib import Path
from markupsafe import Markup, escape
from .paths import ROOT

CATALOG = [dict(item, id=i) for i, item in enumerate(json.loads(
    (Path(__file__).parent / 'guild_achievements.json').read_text(encoding='utf-8')), 1)]
CATEGORIES = tuple(dict.fromkeys(a['category'] for a in CATALOG)) + ('Uncategorized',)
ICON_RE = re.compile(r'^achievement-icons/[A-Z][0-9]{2}\.png$')
MIGRATION = 'guild_achievements_dungeonledger_30_plus_18_v1'


def valid_icon_path(icon):
    value = str(icon or '')
    return value if ICON_RE.fullmatch(value) and (ROOT / 'static' / value).is_file() else None


def achievement_icon_html(icon):
    path = valid_icon_path(icon)
    if path:
        return Markup('<img class="ftc-ach-art" src="/static/' + str(escape(path)) + '" alt="" loading="lazy">')
    return escape(icon or '🏆')


def icon_for_discord(icon):
    return '🏅' if valid_icon_path(icon) else str(icon or '🏆')


def install_catalog(db):
    """Archive the old catalogue once and install 48 canonical badges. Don't delete unlocks."""
    cols = {row[1] for row in db.execute('PRAGMA table_info(achievements)')}
    for column, declaration in (
        ('active', 'INTEGER NOT NULL DEFAULT 1'),
        ('catalog_key', "TEXT NOT NULL DEFAULT ''"),
        ('catalog_origin', "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in cols:
            db.execute(f'ALTER TABLE achievements ADD COLUMN {column} {declaration}')
    db.execute('''CREATE TABLE IF NOT EXISTS critbot_catalog_migrations (
        name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    if not db.execute('SELECT 1 FROM critbot_catalog_migrations WHERE name=?', (MIGRATION,)).fetchone():
        db.execute("UPDATE achievements SET active=0 WHERE catalog_key=''")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auto_rules'").fetchone():
            db.execute("UPDATE auto_rules SET enabled=0 WHERE achievement_id IN (SELECT id FROM achievements WHERE active=0)")
        db.execute('INSERT INTO critbot_catalog_migrations(name) VALUES (?)', (MIGRATION,))
    added = 0
    for a in CATALOG:
        existing = db.execute('SELECT id FROM achievements WHERE catalog_key=?', (a['key'],)).fetchone()
        if not existing:
            existing = db.execute('SELECT id FROM achievements WHERE name=? COLLATE NOCASE', (a['name'],)).fetchone()
        if existing:
            # Preserve ID, past unlocks, Discord reward roles, and other user history.
            db.execute('''UPDATE achievements SET name=?, description=?, rarity=?, points=?,
                icon=?, category=?, verification=?, active=1, catalog_key=?, catalog_origin=?
                WHERE id=?''',
                (a['name'], a['description'], a['rarity'], a['points'], a['icon'], a['category'],
                 a['verification'], a['key'], a['origin'], existing[0]))
        else:
            db.execute('''INSERT INTO achievements
                (name,description,rarity,points,icon,role_id,beta_exclusive,category,verification,active,catalog_key,catalog_origin)
                VALUES(?,?,?,?,?,'',0,?,?,1,?,?)''',
                (a['name'], a['description'], a['rarity'], a['points'], a['icon'],
                 a['category'], a['verification'], a['key'], a['origin']))
            added += 1
    return added
