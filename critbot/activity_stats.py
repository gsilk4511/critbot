"""Read-only activity queries shared by Discord progress and the dashboard."""

def member_stats(db, member_id):
    mid = str(member_id)
    messages = db.execute('SELECT count FROM auto_progress WHERE member_id=?', (mid,)).fetchone()
    voice = db.execute('SELECT seconds FROM auto_voice_progress WHERE member_id=?', (mid,)).fetchone()
    days = db.execute('SELECT COUNT(*) FROM auto_active_days WHERE member_id=?', (mid,)).fetchone()[0]
    awards = db.execute('SELECT COUNT(*),COALESCE(SUM(a.points),0) FROM unlocks u JOIN achievements a ON a.id=u.achievement_id WHERE u.member_id=?', (mid,)).fetchone()
    return dict(messages=int(messages[0]) if messages else 0, voice_seconds=float(voice[0]) if voice else 0,
                days=int(days), unlocks=int(awards[0]), points=int(awards[1]))


def member_progress(db, member_id, stats=None):
    mid = str(member_id)
    stats = stats if stats is not None else member_stats(db, mid)
    settings = db.execute('SELECT enabled,voice_enabled,days_enabled FROM auto_settings WHERE id=1').fetchone()
    tracking = dict(zip(('messages','voice','days'), settings or (0,0,0)))
    rows = db.execute('''SELECT a.id,a.name,a.description,a.rarity,a.icon,a.points,
        r.target,r.kind,r.enabled,
        EXISTS(SELECT 1 FROM unlocks u WHERE u.achievement_id=a.id AND u.member_id=?) AS owned,
        EXISTS(SELECT 1 FROM auto_deliveries d WHERE d.achievement_id=a.id AND d.member_id=?) AS delivered,
        (SELECT q.status FROM award_queue q WHERE q.achievement_id=a.id AND q.member_id=? AND q.action='award'
         ORDER BY q.id DESC LIMIT 1) AS queue_status
        FROM auto_rules r JOIN achievements a ON a.id=r.achievement_id
        ORDER BY r.kind,r.target,a.name COLLATE NOCASE''', (mid,mid,mid)).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        kind=item['kind']
        current={'messages':stats['messages'],'voice':stats['voice_seconds']/60,'days':stats['days']}[kind]
        goal=item['target']
        if item['owned']:
            state='Unlocked'
        elif item['delivered']:
            state={'pending':'Award queued','failed':'Award needs staff review','warning':'Award needs staff review'}.get(item['queue_status'],'Previously processed — not reissued')
        elif not item['enabled']:
            state='Rule paused'
        elif not tracking[kind]:
            state='Tracking paused'
        elif current>=goal:
            state='Target reached — checked on next activity'
        else:
            state='In progress'
        item.update(current=current,percent=min(100,int(current/goal*1000)/10) if goal else 0,
                    unit={'messages':'messages','voice':'voice minutes','days':'active days'}[kind],
                    state=state,tracking=bool(tracking[kind]))
        result.append(item)
    return result


def guild_roster(db):
    rows=db.execute('''WITH days AS (SELECT member_id,COUNT(*) AS total FROM auto_active_days GROUP BY member_id),
        awards AS (SELECT u.member_id,COUNT(*) AS total,COALESCE(SUM(a.points),0) AS points
                   FROM unlocks u JOIN achievements a ON a.id=u.achievement_id GROUP BY u.member_id)
        SELECT m.member_id,m.display_name,m.username,COALESCE(p.count,0) AS messages,
            COALESCE(v.seconds,0) AS voice_seconds,COALESCE(d.total,0) AS days,
            COALESCE(a.total,0) AS unlocks,COALESCE(a.points,0) AS points
        FROM member_directory m LEFT JOIN auto_progress p ON p.member_id=m.member_id
        LEFT JOIN auto_voice_progress v ON v.member_id=m.member_id
        LEFT JOIN days d ON d.member_id=m.member_id LEFT JOIN awards a ON a.member_id=m.member_id
        WHERE m.is_bot=0 ORDER BY m.display_name COLLATE NOCASE,m.member_id''').fetchall()
    return [dict(r) for r in rows]
