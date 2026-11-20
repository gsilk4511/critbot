"""Dashboard admin control to request an immediate Discord channel directory sync."""
from flask import Blueprint, abort, flash, g, redirect, request, url_for, render_template
from .channel_overrides import init_channel_sync, channel_id


def blueprint(connect):
    bp = Blueprint('channels', __name__)

    def authorized():
        access=g.dashboard_access
        return access['level'] in ('owner','pope') or bool(set(access['permissions']) & {'automation','suggestions_board','events_manage'})

    @bp.get('/channels')
    def home():
        if not authorized(): abort(403)
        with connect() as db:
            init_channel_sync(db)
            state=db.execute('SELECT * FROM channel_sync_requests WHERE id=1').fetchone()
            texts=db.execute('SELECT * FROM auto_channel_directory ORDER BY name').fetchall()
            voice=db.execute('SELECT * FROM auto_voice_directory ORDER BY name').fetchall()
            announcement=db.execute('SELECT announcement_id FROM channel_route_overrides WHERE id=1').fetchone()[0]
        return render_template('channels.html',sync=state,channels=texts,voice=voice,announcement_id=announcement)

    @bp.post('/channels/refresh')
    def refresh():
        if not authorized(): abort(403)
        with connect() as db:
            init_channel_sync(db)
            db.execute("UPDATE channel_sync_requests SET requested_at=CURRENT_TIMESTAMP, status='pending', detail='' WHERE id=1")
        flash('Channel refresh requested. If the Discord bot is online, it will pick this up shortly.','success')
        return redirect(url_for('channels.home'))
    @bp.post('/channels/announcement')
    def announcement():
        access=g.dashboard_access
        if access['level'] not in ('owner','pope'): abort(403)
        incoming=request.form.get('announcement_id','').strip()
        try:
            selected=channel_id(incoming) if incoming else ''
        except ValueError as exc:
            flash(str(exc),'error')
            return redirect(url_for('channels.home'))
        with connect() as db:
            init_channel_sync(db)
            db.execute('UPDATE channel_route_overrides SET announcement_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=1',(selected,))
            db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                (access['discord_id'],'channels','announcement_route_changed',selected or 'Default from environment'))
        flash('Announcement destination updated. CritBot will check its permissions when posting.','success')
        return redirect(url_for('channels.home'))
    return bp
