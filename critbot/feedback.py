"""Private guild feedback inbox, intentionally separate from public suggestion posts."""
from flask import Blueprint, request, g, abort, flash, redirect, url_for, render_template, session
from .security import can

CATEGORIES = {'bot': 'CritBot', 'discord': 'Discord server', 'guild': 'Guild generally'}
KINDS = {'bug': 'Bug / issue', 'idea': 'Suggestion / idea', 'concern': 'Concern',
         'praise': 'Something great', 'question': 'Question', 'other': 'Other'}
STATUSES = {'new', 'reviewed', 'resolved'}


def init_feedback(db):
    db.execute('''CREATE TABLE IF NOT EXISTS member_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
        kind TEXT NOT NULL, identity_mode TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new', response TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT NOT NULL DEFAULT '')''')


def blueprint(connect):
    bp = Blueprint('feedback', __name__)

    def manager():
        return can(g.dashboard_access, 'feedback_manage')

    @bp.route('/feedback', methods=['GET', 'POST'])
    def home():
        if request.method == 'POST':
            category = request.form.get('category', '')
            kind = request.form.get('kind', '')
            mode = request.form.get('identity_mode', 'discord')
            body = request.form.get('body', '').strip()
            if category not in CATEGORIES or kind not in KINDS or mode not in ('anonymous','discord','custom'):
                flash('Choose valid feedback options.', 'error')
                return redirect(url_for('feedback.home'))
            if len(body)<5 or len(body)>2500:
                flash('Feedback must contain 5–2,500 characters.', 'error')
                return redirect(url_for('feedback.home'))
            if mode == 'anonymous':
                name = ''  # Do not store a Discord ID for anonymous submissions.
            elif mode == 'discord':
                name = (g.dashboard_access['display_name'] or 'Discord member')[:80]
            else:
                name = request.form.get('custom_name','').strip()[:80]
                if not name:
                    flash('Enter a name, or use Anonymous.', 'error')
                    return redirect(url_for('feedback.home'))
            with connect() as db:
                db.execute('INSERT INTO member_feedback(category,kind,identity_mode,display_name,body) VALUES(?,?,?,?,?)',
                           (category,kind,mode,name,body))
            flash('Feedback submitted. Thank you for helping improve the guild.', 'success')
            return redirect(url_for('feedback.home'))
        return render_template('feedback.html',categories=CATEGORIES,kinds=KINDS,manager=manager())

    @bp.get('/feedback/review')
    def review():
        if not manager():abort(403)
        with connect() as db:
            items=db.execute("SELECT * FROM member_feedback ORDER BY CASE status WHEN 'new' THEN 0 WHEN 'reviewed' THEN 1 ELSE 2 END,id DESC LIMIT 500").fetchall()
        counts={'new':0,'reviewed':0,'resolved':0}
        for item in items:counts[item['status']]=counts.get(item['status'],0)+1
        return render_template('feedback_review.html',items=items,counts=counts,categories=CATEGORIES,kinds=KINDS)

    @bp.post('/feedback/<int:feedback_id>/status')
    def set_status(feedback_id):
        if not manager(): abort(403)
        status=request.form.get('status','')
        if status not in STATUSES:abort(400)
        with connect() as db:
            cur=db.execute("UPDATE member_feedback SET status=?,resolved_at=CASE WHEN ?='resolved' THEN CURRENT_TIMESTAMP ELSE '' END WHERE id=?",
                           (status,status,feedback_id))
            if not cur.rowcount: abort(404)
        flash('Feedback status updated.', 'success')
        return redirect(url_for('feedback.review'))
    return bp
