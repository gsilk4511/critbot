"""Private dashboard notifications and member-to-member positive commendations.

These are member-submitted endorsements, not verified claims about character.
No Discord DMs, no background jobs, no tracked presence.
"""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

TRAITS = (
    ('Helpful', 'Hand to someone who needs it', '🤝'),
    ('Welcoming', 'Makes newcomers feel at home', '🌟'),
    ('Patient', 'Takes time to explain and teach', '📖'),
    ('Reliable', 'Shows up and follows through', '🛡'),
    ('Leadership', 'Organizes and guides others', '⚔'),
    ('Fun to Play With', 'Makes guild activities enjoyable', '🎉'),
)
TRAIT_NAMES = {t[0] for t in TRAITS}


def init_social(db):
    db.execute('''CREATE TABLE IF NOT EXISTS hub_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipient_id TEXT NOT NULL,
        actor_id TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'activity',
        title TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        link TEXT NOT NULL DEFAULT '/hub',
        read_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_hub_notice_user ON hub_notifications(recipient_id,read_at,id DESC)')
    db.execute('''CREATE TABLE IF NOT EXISTS member_commendations (
        author_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        trait TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(author_id,target_id)
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_member_commendations_target ON member_commendations(target_id,trait)')


def notify(db, recipient_id, actor_id, kind, title, message='', link='/hub'):
    recipient_id, actor_id = str(recipient_id),str(actor_id)
    if not recipient_id or recipient_id==actor_id:return
    group={'request':'notify_requests','commendation':'notify_commendations','group':'notify_groups','event':'notify_events','social':'notify_social'}.get(kind)
    if group:
        try:
            prefs=db.execute(f'SELECT {group} FROM member_hub_settings WHERE member_id=?',(recipient_id,)).fetchone()
            if prefs is not None and not prefs[0]:return
        except Exception: pass  # Older databases may not have initialized settings yet.
    if not link.startswith('/') or link.startswith('//') or '\\' in link:link='/hub'
    db.execute('''INSERT INTO hub_notifications(recipient_id,actor_id,kind,title,message,link)
        VALUES(?,?,?,?,?,?)''',(recipient_id,actor_id,str(kind)[:32],str(title)[:120],str(message)[:350],link[:256]))


def inbox_rows(db, user, limit=25):
    return [dict(r) for r in db.execute('''SELECT id,kind,title,message,link,read_at,created_at
        FROM hub_notifications WHERE recipient_id=? ORDER BY id DESC LIMIT ?''',(str(user),limit))]


def unread_count(db, user):
    return db.execute('SELECT COUNT(*) FROM hub_notifications WHERE recipient_id=? AND read_at IS NULL',(str(user),)).fetchone()[0]


def commendation_summary(db, target_id):
    rows=db.execute('''SELECT trait,COUNT(*) n FROM member_commendations WHERE target_id=? GROUP BY trait ORDER BY n DESC,trait''',(str(target_id),)).fetchall()
    return [dict(row) for row in rows]


def give_commendation(db, author_id, target_id, trait):
    author_id, target_id=str(author_id),str(target_id)
    if author_id==target_id:raise ValueError('You cannot commend yourself.')
    if trait not in TRAIT_NAMES:raise ValueError('Choose a valid commendation.')
    if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(target_id,)).fetchone():
        raise ValueError('That member is no longer in the guild directory.')
    if not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(author_id,)).fetchone():
        raise ValueError('Your account must be in the guild member directory.')
    prior=db.execute('SELECT trait FROM member_commendations WHERE author_id=? AND target_id=?',(author_id,target_id)).fetchone()
    if prior and prior['trait']==trait:raise ValueError('You already gave this commendation.')
    db.execute('''INSERT INTO member_commendations(author_id,target_id,trait) VALUES(?,?,?)
        ON CONFLICT(author_id,target_id) DO UPDATE SET trait=excluded.trait,updated_at=CURRENT_TIMESTAMP''',
        (author_id,target_id,trait))
    if not prior:
        notify(db,target_id,author_id,'commendation','Someone recognized you','A guildmate left a positive commendation on your profile.',f'/members/{target_id}')
    return bool(prior)


def blueprint(connect):
    bp=Blueprint('social',__name__)

    @bp.get('/hub/notifications')
    def inbox():
        user=g.dashboard_access['discord_id']
        with connect() as db:
            rows=inbox_rows(db,user,50)
        return render_template('hub_notifications.html',notices=rows)

    @bp.post('/hub/notifications/read-all')
    def mark_all():
        user=g.dashboard_access['discord_id']
        with connect() as db:
            db.execute('UPDATE hub_notifications SET read_at=CURRENT_TIMESTAMP WHERE recipient_id=? AND read_at IS NULL',(user,))
        return redirect(url_for('social.inbox'))

    @bp.post('/hub/notifications/<int:notice_id>/read')
    def mark_one(notice_id):
        user=g.dashboard_access['discord_id']
        with connect() as db:
            row=db.execute('SELECT link FROM hub_notifications WHERE id=? AND recipient_id=?',(notice_id,user)).fetchone()
            if row is None:abort(404)
            db.execute('UPDATE hub_notifications SET read_at=COALESCE(read_at,CURRENT_TIMESTAMP) WHERE id=? AND recipient_id=?',(notice_id,user))
        return redirect(row['link'] if row['link'].startswith('/') and not row['link'].startswith('//') else '/hub')

    @bp.post('/members/<member_id>/commend')
    def commend(member_id):
        user=g.dashboard_access['discord_id']
        if not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:abort(404)
        try:
            with connect() as db:
                update=give_commendation(db,user,member_id,request.form.get('trait',''))
            flash('Commendation updated.' if update else 'Commendation sent. Thanks for recognizing a guildmate!','success')
        except ValueError as exc:flash(str(exc),'error')
        return redirect(url_for('member_profile',member_id=member_id)+'#commendations')

    @bp.post('/members/<member_id>/commend/remove')
    def withdraw(member_id):
        user=g.dashboard_access['discord_id']
        if not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20:abort(404)
        with connect() as db:
            db.execute('DELETE FROM member_commendations WHERE target_id=? AND author_id=?',(member_id,user))
        flash('Your commendation was withdrawn.','success')
        return redirect(url_for('member_profile',member_id=member_id)+'#commendations')

    return bp
