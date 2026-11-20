from flask import Blueprint,render_template,request,redirect,url_for,flash,abort,g
from .store import submit,vote
from .store import STATUSES,totals
from ...channel_overrides import selected_channel

def blueprint(connect):
    bp=Blueprint('suggestions',__name__)
    @bp.get('/suggestions')
    def home():
        status=request.args.get('status','all');sort=request.args.get('sort','newest')
        can=lambda key:g.dashboard_access['level'] in ('owner','pope') or key in g.dashboard_access['permissions']
        can_archive=can('suggestions_archive')
        can_delete=can('suggestions_delete')
        if status not in ('all','archived')+STATUSES:status='all'
        if status=='archived' and not (can_archive or can_delete):abort(403)
        with connect() as db:
            board=db.execute('SELECT * FROM suggestion_board WHERE id=1').fetchone()
            rows=db.execute('SELECT * FROM guild_suggestions ORDER BY id DESC').fetchall()
            items=[dict(row,**totals(db,row['id'])) for row in rows
                   if (bool(row['archived']) if status=='archived' else not row['archived'])
                   and (status in ('all','archived') or row['status']==status)]
            channels=db.execute('SELECT * FROM auto_channel_directory ORDER BY name').fetchall()
            status_counts=dict(db.execute('SELECT status,COUNT(*) FROM guild_suggestions WHERE archived=0 GROUP BY status').fetchall())
            archived_count=db.execute('SELECT COUNT(*) FROM guild_suggestions WHERE archived=1').fetchone()[0]
        if sort=='top':items.sort(key=lambda i:(i['score'],i['id']),reverse=True)
        counts={v:status_counts.get(v,0) for v in STATUSES}
        return render_template('suggestions.html',items=items,board=board,channels=channels,channel_names={str(c['channel_id']):'#'+str(c['name']) for c in channels},status=status,sort=sort,
           counts=counts,archived_count=archived_count,can_archive=can_archive,can_delete=can_delete,
           can_moderate=can('suggestions_manage'),can_board=can('suggestions_board'))
    @bp.post('/suggestions/board')
    def board():
        try:
            button_channel=selected_channel(request.form, 'channel_id')
            feed_channel=selected_channel(request.form, 'results_channel_id')
        except ValueError as err:
            flash(str(err), 'error')
            return redirect(url_for('suggestions.home'))
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if button_channel==feed_channel:
                flash('Choose two DIFFERENT Discord text channels: one for the Submit Idea button and another for published suggestions.','error')
                return redirect(url_for('suggestions.home'))
            row=db.execute('SELECT * FROM suggestion_board WHERE id=1').fetchone()
            if row['state'] in ('queued','posting'):
                flash('A Discord button change is already queued. Check back shortly.','error')
            elif row['channel_id']==button_channel and row['state']=='posted':
                # A feed-only change never republishes the button or invalidates it.
                if row['results_channel_id'] == feed_channel:
                    flash('Both suggestion channels are already configured.','success')
                else:
                    db.execute('UPDATE suggestion_board SET results_channel_id=?,feed_needs_sync=1 WHERE id=1',(feed_channel,))
                    db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                        (g.dashboard_access['discord_id'],'suggestions','suggestion_feed_changed',f'New suggestions: {feed_channel}'))
                    flash('Suggestion feed updated. New ideas will post to the selected channel. Existing ideas and the Submit Idea button stay where they are.','success')
            else:
                # Moving the submission button invalidates and retires the old button,
                # but never touches already-published suggestion posts or votes.
                if row['message_id']:
                    db.execute('INSERT INTO suggestion_board_retire(guild_id,channel_id,message_id) VALUES(?,?,?)',
                               (row['guild_id'],row['channel_id'],row['message_id']))
                db.execute("UPDATE suggestion_board SET channel_id=?,results_channel_id=?,guild_id='',message_id='',state='queued',last_error='',feed_needs_sync=0 WHERE id=1",
                           (button_channel,feed_channel))
                db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                    (g.dashboard_access['discord_id'],'suggestions','suggestion_channels_changed',f'Button: {button_channel}; feed: {feed_channel}'))
                flash('Discord suggestion button queued. Suggestions will post separately in the chosen feed. Existing ideas and votes stay intact.','success')
        return redirect(url_for('suggestions.home'))
    @bp.post('/suggestions/new')
    def create():
        # Discord OAuth supplies the author identity. No client-supplied user IDs.
        user=g.dashboard_access
        with connect() as db:
            board=db.execute('SELECT * FROM suggestion_board WHERE id=1').fetchone()
            if board is None or board['state']!='posted' or not board['guild_id'] or not board['message_id']:
                flash('An officer must publish the Discord suggestion board before ideas can be posted.','error')
                return redirect(url_for('suggestions.home'))
            try:
                sid=submit(db,request.form.get('title',''),request.form.get('body',''),user['discord_id'],
                    user['display_name'],board['guild_id'],board['channel_id'],board['message_id'])
            except ValueError as exc:
                flash(str(exc),'error');return redirect(url_for('suggestions.home'))
        flash('Suggestion saved. CritBot will post it to Discord shortly.','success')
        return redirect(url_for('suggestions.detail',sid=sid))
    @bp.post('/suggestions/<int:sid>/vote')
    def vote_web(sid):
        user=g.dashboard_access
        try:direction=int(request.form.get('direction','0'))
        except ValueError:abort(400)
        with connect() as db:
            item=db.execute('SELECT * FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if item is None:abort(404)
            if item['archived'] or item['delete_state']:
                flash('This suggestion is archived and no longer accepts votes.','error')
                return redirect(url_for('suggestions.home'))
            try:
                result=vote(db,sid,user['discord_id'],direction,item['guild_id'],item['channel_id'],item['message_id'])
            except ValueError as exc:
                flash(str(exc),'error');return redirect(url_for('suggestions.detail',sid=sid))
        flash(result+' The Discord post will update shortly.','success')
        return redirect(url_for('suggestions.detail',sid=sid))
    @bp.get('/suggestions/<int:sid>')
    def detail(sid):
        with connect() as db:
            item=db.execute('SELECT * FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if item is None:abort(404)
            counts=totals(db,sid)
        can=lambda key:g.dashboard_access['level'] in ('owner','pope') or key in g.dashboard_access['permissions']
        if item['archived'] and not (can('suggestions_archive') or can('suggestions_delete')):abort(404)
        return render_template('suggestion_detail.html',item=item,counts=counts,statuses=STATUSES,
            can_moderate=can('suggestions_manage'),can_archive=can('suggestions_archive'),can_delete=can('suggestions_delete'))
    @bp.post('/suggestions/<int:sid>')
    def update(sid):
        status=request.form.get('status');note=request.form.get('staff_note','').strip()
        category=request.form.get('category','General')
        priority=request.form.get('priority','normal')
        assigned_to=request.form.get('assigned_to','').strip()
        internal_note=request.form.get('internal_note','').strip()
        if status not in STATUSES or len(note)>1000 or category not in ('General','Events','Community','CritBot','Guild resources') or priority not in ('low','normal','high') or len(assigned_to)>80 or len(internal_note)>1000:abort(400)
        with connect() as db:
            current=db.execute('SELECT archived,delete_state FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if current is None:abort(404)
            if current['archived'] or current['delete_state']:abort(409)
            db.execute('''UPDATE guild_suggestions SET status=?,staff_note=?,category=?,priority=?,assigned_to=?,internal_note=?,revision=revision+1 WHERE id=?''',(status,note,category,priority,assigned_to,internal_note,sid))
        flash('Decision saved. Discord will update when Critbot is online.','success');return redirect(url_for('suggestions.detail',sid=sid))
    @bp.post('/suggestions/<int:sid>/retry')
    def retry(sid):
        with connect() as db:
            item=db.execute('SELECT * FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if item is None:abort(404)
            if item['delete_state']:abort(409)
            if item['message_id']:db.execute("UPDATE guild_suggestions SET revision=revision+1,last_error='' WHERE id=?",(sid,))
            elif item['publish_state'] in ('failed','uncertain'):db.execute("UPDATE guild_suggestions SET publish_state='queued',last_error='' WHERE id=?",(sid,))
        return redirect(url_for('suggestions.detail',sid=sid))

    @bp.post('/suggestions/<int:sid>/archive')
    def archive(sid):
        with connect() as db:
            item=db.execute('SELECT archived,delete_state FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if item is None:abort(404)
            if item['delete_state']:abort(409)
            db.execute("""UPDATE guild_suggestions SET archived=1,archived_by=?,archived_at=CURRENT_TIMESTAMP,
               revision=revision+1 WHERE id=?""",(g.dashboard_access['discord_id'],sid))
            db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                (g.dashboard_access['discord_id'],str(sid),'suggestion_archived','Archived from dashboard'))
        flash('Suggestion archived. Its Discord voting buttons will be disabled shortly.','success')
        return redirect(url_for('suggestions.home',status='archived'))

    @bp.post('/suggestions/<int:sid>/restore')
    def restore(sid):
        with connect() as db:
            item=db.execute('SELECT archived,delete_state FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if item is None:abort(404)
            if item['delete_state']:abort(409)
            db.execute("""UPDATE guild_suggestions SET archived=0,archived_by='',archived_at=NULL,
                revision=revision+1 WHERE id=?""",(sid,))
            db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                (g.dashboard_access['discord_id'],str(sid),'suggestion_restored','Restored to active inbox'))
        flash('Suggestion restored to the active inbox.','success')
        return redirect(url_for('suggestions.detail',sid=sid))

    @bp.route('/suggestions/<int:sid>/delete',methods=['GET','POST'])
    def delete(sid):
        with connect() as db:
            item=db.execute('SELECT * FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if item is None:abort(404)
            votes=db.execute('SELECT COUNT(*) FROM suggestion_votes WHERE suggestion_id=?',(sid,)).fetchone()[0]
        if request.method=='GET':return render_template('suggestion_delete.html',item=item,votes=votes)
        if request.form.get('confirm_title','').strip()!=item['title']:
            flash('Type the exact suggestion title to confirm permanent deletion.','error')
            return redirect(url_for('suggestions.delete',sid=sid))
        with connect() as db:
            item=db.execute('SELECT * FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if item is None:abort(404)
            if not item['message_id'] and item['publish_state'] in ('posting','uncertain'):
                flash('Discord publication is uncertain. Check the channel and resolve the post before deleting. You can archive it now.','error')
                return redirect(url_for('suggestions.detail',sid=sid))
            db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                (g.dashboard_access['discord_id'],str(sid),'suggestion_delete_requested',item['title'][:200]))
            if not item['message_id']:
                db.execute('DELETE FROM suggestion_votes WHERE suggestion_id=?',(sid,))
                db.execute('DELETE FROM guild_suggestions WHERE id=?',(sid,))
                flash('Unpublished suggestion permanently deleted.','success')
                return redirect(url_for('suggestions.home'))
            db.execute("""UPDATE guild_suggestions SET archived=1,archived_by=?,archived_at=CURRENT_TIMESTAMP,
                delete_state='queued',delete_requested_by=?,revision=revision+1,last_error='' WHERE id=?""",
                (g.dashboard_access['discord_id'],g.dashboard_access['discord_id'],sid))
        flash('Deletion queued. CritBot will remove the Discord post first, then erase the suggestion and its votes.','success')
        return redirect(url_for('suggestions.home',status='archived'))

    @bp.post('/suggestions/<int:sid>/retry-delete')
    def retry_delete(sid):
        with connect() as db:
            row=db.execute('SELECT delete_state FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
            if row is None:abort(404)
            if row['delete_state']!='failed':abort(409)
            db.execute("UPDATE guild_suggestions SET delete_state='queued',last_error='' WHERE id=?",(sid,))
            db.execute('INSERT INTO dashboard_audit(actor_id,target_id,action,detail) VALUES(?,?,?,?)',
                (g.dashboard_access['discord_id'],str(sid),'suggestion_delete_retry','Retry Discord post removal'))
        flash('Discord deletion retry queued.','success')
        return redirect(url_for('suggestions.detail',sid=sid))
    return bp
