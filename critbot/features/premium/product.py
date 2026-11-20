import csv,io,re,time
from flask import Blueprint,render_template,request,redirect,url_for,flash,abort,Response
from .store import allowed
from ...activity_stats import guild_roster

def blueprint(connect):
    bp=Blueprint('product',__name__)
    @bp.get('/guild/tools')
    def tools():
        return render_template('guild_tools.html')
    @bp.route('/guild/branding',methods=['GET','POST'])
    def brand():
        with connect() as db:
            if request.method=='POST':
                name=request.form.get('name','').strip();tagline=request.form.get('tagline','').strip();accent=request.form.get('accent','');theme=request.form.get('theme','')
                if not name or len(name)>30 or len(tagline)>30 or not re.fullmatch(r'#[0-9a-fA-F]{6}',accent) or theme not in ('crest','minimal'):abort(400)
                db.execute('UPDATE guild_branding SET name=?,tagline=?,accent=?,theme=? WHERE id=1',(name,tagline,accent,theme));flash('Unlock-card style saved. Preview it in Cards.','success');return redirect(url_for('product.brand'))
            brand=db.execute('SELECT * FROM guild_branding WHERE id=1').fetchone()
        return render_template('brand.html',brand=brand)
    @bp.route('/guild/seasons',methods=['GET','POST'])
    def seasons():
        with connect() as db:
            if request.method=='POST':
                title=request.form.get('title','').strip();metric=request.form.get('metric');days=request.form.get('days','')
                if not title or len(title)>80 or metric not in ('messages','voice') or not days.isdecimal() or not 1<=int(days)<=31:abort(400)
                now=time.time();db.execute('INSERT INTO guild_seasons(title,metric,starts,ends) VALUES(?,?,?,?)',(title,metric,now,now+int(days)*86400));flash('Competition started. Only new, tracked activity counts.','success');return redirect(url_for('product.seasons'))
            seasons=[dict(s) for s in db.execute('SELECT * FROM guild_seasons ORDER BY id DESC')]
            for s in seasons:
                s['ended']=s['closed'] or s['ends']<=time.time()
                s['leaders']=[dict(row) for row in db.execute("SELECT scores.member_id,scores.score,COALESCE(m.display_name,scores.member_id) AS name FROM season_scores scores LEFT JOIN member_directory m ON m.member_id=scores.member_id WHERE season_id=? AND score>0 ORDER BY score DESC,scores.member_id LIMIT 20",(s['id'],))]
        return render_template('seasons.html',seasons=seasons)
    @bp.post('/guild/seasons/<int:sid>/close')
    def close(sid):
        with connect() as db:db.execute('UPDATE guild_seasons SET closed=1 WHERE id=?',(sid,))
        flash('Competition closed. Results are preserved.','success');return redirect(url_for('product.seasons'))
    @bp.get('/guild/export')
    def export():
        with connect() as db:rows=guild_roster(db)
        stream=io.StringIO();writer=csv.writer(stream);keys=['member_id','display_name','points','unlocks','messages','voice_seconds','days'];writer.writerow(keys)
        for row in rows:
            values=[row[k] for k in keys];values=["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in values];writer.writerow(values)
        return Response(stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=critbot-stats.csv'})
    return bp
