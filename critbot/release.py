"""Reversible-before-commit one-time launch cleanup for CritBot.

Never run against a database without both founding achievements. Keeps their IDs,
unlocks, awards, and reward roles intact. Snapshot backup occurs before mutation.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

KEEP = frozenset(('beta member', 'crit me if you can'))
MIGRATION = 'launch_1_2_keep_founding_achievements'


def delete_achievement_records(db, ids):
    """Remove one or more achievements and their references within one DB transaction."""
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    marks = ','.join('?' for _ in ids)
    for table in ('auto_deliveries', 'auto_rules', 'award_queue', 'unlocks', 'bulk_batches'):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists:
            db.execute(f'DELETE FROM {table} WHERE achievement_id IN ({marks})', ids)
    db.execute(f'DELETE FROM achievements WHERE id IN ({marks})', ids)
    return len(ids)


def launch_cleanup(db_path):
    """Called before bot startup; creates DB backup and prunes test achievements once."""
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise RuntimeError(f'Live database is missing: {db_path}; aborting without creating a blank one.')
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE IF NOT EXISTS critbot_launch_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, notes TEXT NOT NULL)')
        if conn.execute('SELECT 1 FROM critbot_launch_migrations WHERE name=?',(MIGRATION,)).fetchone():
            return {'already_applied': True, 'removed': 0, 'backup': None}
        existing = conn.execute('SELECT id,name,role_id FROM achievements ORDER BY id').fetchall()
        present = {r['name'].strip().casefold() for r in existing}
        missing = KEEP - present
        if missing:
            raise RuntimeError('Refusing achievement cleanup: required founding achievements missing: '+', '.join(sorted(missing)))
        remove_ids = [r['id'] for r in existing if r['name'].strip().casefold() not in KEEP]
        for entry in existing:
            if entry['id'] in remove_ids and entry['role_id']:
                assigned = conn.execute('SELECT COUNT(*) FROM unlocks WHERE achievement_id=?',(entry['id'],)).fetchone()[0]
                if assigned:
                    raise RuntimeError(f"Cannot automatically remove '{entry['name']}': it has a Discord reward role and {assigned} unlock(s). Revoke rewards first to avoid orphaned Discord roles.")
        # Do not need a database backup if nothing needs removing, but migration stays marked.
        backup = None
        if remove_ids:
            backup_dir=db_path.parent/'backups'
            backup_dir.mkdir(parents=True,exist_ok=True)
            timestamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            backup=backup_dir/f'critbot_pre_launch_cleanup_{timestamp}.db'
            with sqlite3.connect(str(backup)) as target:
                conn.backup(target)
            with sqlite3.connect(str(backup)) as check:
                if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise RuntimeError('Database backup integrity check failed; refusing cleanup.')
        try:
            conn.execute('BEGIN IMMEDIATE')
            delete_achievement_records(conn, remove_ids)
            left={r[0].strip().casefold() for r in conn.execute('SELECT name FROM achievements')}
            if left != KEEP:
                raise RuntimeError('Unexpected achievements after cleanup; rolling back.')
            conn.execute('INSERT INTO critbot_launch_migrations(name,notes) VALUES(?,?)',
                (MIGRATION,f'Preserved Beta Member and Crit Me If You Can; removed {len(remove_ids)} other achievements.'))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return {'already_applied':False, 'removed':len(remove_ids),'backup':str(backup) if backup else None}
    finally:
        conn.close()
