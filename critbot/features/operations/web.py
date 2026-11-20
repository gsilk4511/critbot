"""Guild operations tools, intentionally private to granted officers.

Conduct entries are brief, append-only notes with follow-ups; they are not formal
investigations. Treasury is an officers' MANUAL ledger, not a Discord/WoW bank sync.
"""
import csv, io
from flask import Response
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g

CATEGORIES=('Conduct concern','Conflict','Member support','Follow-up','Other')
SEVERITIES=('low','normal','high')
CASE_STATUSES=('open','following_up','closed')
LEDGER_TYPES=('deposit','expense','correction_in','correction_out')

def init_operations(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS conduct_cases (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      member_id TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL,
      category TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'normal',
      summary TEXT NOT NULL, next_step TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'open', created_by TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS conduct_followups (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      case_id INTEGER NOT NULL, body TEXT NOT NULL, status_after TEXT NOT NULL,
      recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(case_id) REFERENCES conduct_cases(id)
    );
    CREATE TABLE IF NOT EXISTS treasury_ledger (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      direction TEXT NOT NULL, amount_copper INTEGER NOT NULL CHECK(amount_copper>0),
      purpose TEXT NOT NULL, member_name TEXT NOT NULL DEFAULT '',
      recorded_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    ''')
    columns={row[1] for row in db.execute('PRAGMA table_info(treasury_ledger)')}
    for column,decl in [('member_id',"TEXT NOT NULL DEFAULT ''"),('counterparty_role',"TEXT NOT NULL DEFAULT ''")]:
        if column not in columns:db.execute(f'ALTER TABLE treasury_ledger ADD COLUMN {column} {decl}')

def coins(copper):
    value=abs(int(copper));g,rem=divmod(value,10000);s,c=divmod(rem,100)
    return f'{g:,}g {s:02d}s {c:02d}c'

def gold_text(copper):
    return coins(copper)

def blueprint(connect):
    bp=Blueprint('operations',__name__)
    @bp.get('/conduct')
    def home():
        status=request.args.get('status','open')
        if status not in ('open','following_up','closed','all'):status='open'
        with connect() as db:
            cases=[dict(r) for r in db.execute('SELECT * FROM conduct_cases'+('' if status=='all' else ' WHERE status=?')+' ORDER BY CASE priority WHEN "high" THEN 0 WHEN "normal" THEN 1 ELSE 2 END,updated_at DESC,id DESC',(() if status=='all' else (status,)))]
            members=db.execute('SELECT member_id,display_name FROM member_directory WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE LIMIT 5000').fetchall()
            followups={r['id']:[] for r in cases}
            for note in db.execute('SELECT * FROM conduct_followups ORDER BY id DESC'):
                if note['case_id'] in followups:followups[note['case_id']].append(dict(note))
            total=db.execute("SELECT COUNT(*) FROM conduct_cases WHERE status!='closed'").fetchone()[0]
        return render_template('conduct.html',cases=cases,followups=followups,members=members,status=status,open_count=total,categories=CATEGORIES,can_edit='conduct_manage' in g.dashboard_access['permissions'] or g.dashboard_access['level'] in ('owner','pope'))

    @bp.post('/conduct/new')
    def create():
        mid=request.form.get('member_id','').strip()
        subject=request.form.get('subject','').strip()
        category=request.form.get('category','')
        severity=request.form.get('priority','normal')
        summary=request.form.get('summary','').strip()
        next_step=request.form.get('next_step','').strip()
        if mid and (not mid.isascii() or not mid.isdecimal() or len(mid)>20):abort(400)
        if not subject or len(subject)>80 or category not in CATEGORIES or severity not in SEVERITIES or not summary or len(summary)>600 or len(next_step)>300:abort(400)
        with connect() as db:
            if mid and not db.execute('SELECT 1 FROM member_directory WHERE member_id=? AND is_bot=0',(mid,)).fetchone():abort(400)
            db.execute('''INSERT INTO conduct_cases(member_id,subject,category,priority,summary,next_step,created_by)
                          VALUES(?,?,?,?,?,?,?)''',(mid,subject,category,severity,summary,next_step,g.dashboard_access['discord_id']))
        flash('Private conduct note saved. Only officers with Conduct access can view it.','success')
        return redirect(url_for('operations.home'))

    @bp.post('/conduct/<int:case_id>/followup')
    def update(case_id):
        body=request.form.get('body','').strip()
        status=request.form.get('status','')
        next_step=request.form.get('next_step','').strip()
        if not body or len(body)>600 or status not in CASE_STATUSES or len(next_step)>300:abort(400)
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM conduct_cases WHERE id=?',(case_id,)).fetchone():abort(404)
            db.execute('INSERT INTO conduct_followups(case_id,body,status_after,recorded_by) VALUES(?,?,?,?)',
                       (case_id,body,status,g.dashboard_access['discord_id']))
            db.execute('UPDATE conduct_cases SET status=?,next_step=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                       (status,next_step,case_id))
        flash('Follow-up saved. Previous notes remain in the history.','success')
        return redirect(url_for('operations.home',status='all'))

    @bp.get('/treasury')
    def treasury_home():
        with connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM treasury_ledger ORDER BY id DESC LIMIT 500')]
            balance=db.execute("SELECT COALESCE(SUM(CASE WHEN direction IN ('deposit','correction_in') THEN amount_copper ELSE -amount_copper END),0) FROM treasury_ledger").fetchone()[0]
            members=[dict(x) for x in db.execute('SELECT member_id,display_name FROM member_directory WHERE is_bot=0 ORDER BY display_name COLLATE NOCASE LIMIT 5000')]
        for entry in rows:entry['amount']=coins(entry['amount_copper'])
        return render_template('treasury.html',entries=rows,balance=('-' if balance<0 else '')+coins(balance),members=members,
            can_edit=('treasury_manage' in g.dashboard_access['permissions'] or g.dashboard_access['level'] in ('owner','pope')))

    @bp.post('/treasury/record')
    def record():
        kind=request.form.get('direction','')
        purpose=request.form.get('purpose','').strip()
        member_id=request.form.get('member_id','').strip()
        if kind not in LEDGER_TYPES or not purpose or len(purpose)>200:abort(400)
        if member_id and (not member_id.isascii() or not member_id.isdecimal() or len(member_id)>20):abort(400)
        try:
            gold,silver,copper=[int(request.form.get(k,'')) for k in ('gold','silver','copper')]
        except (TypeError,ValueError):abort(400)
        if not 0<=gold<=10000000 or not 0<=silver<=99 or not 0<=copper<=99:abort(400)
        amount=gold*10000+silver*100+copper
        if amount<=0:abort(400)
        role={'deposit':'Depositor','expense':'Recipient','correction_in':'Contributor','correction_out':'Recipient'}[kind]
        with connect() as db:
            member=db.execute('SELECT display_name FROM member_directory WHERE member_id=? AND is_bot=0',(member_id,)).fetchone() if member_id else None
            if member_id and not member:abort(400)
            db.execute('INSERT INTO treasury_ledger(direction,amount_copper,purpose,member_name,recorded_by,member_id,counterparty_role) VALUES(?,?,?,?,?,?,?)',
                (kind,amount,purpose,member['display_name'] if member else '',g.dashboard_access['discord_id'],member_id,role))
        flash('Treasury transaction recorded. This does not transfer in-game funds.','success')
        return redirect(url_for('operations.treasury_home'))

    @bp.get('/treasury/export.csv')
    def treasury_export():
        # Spreadsheet formula injection protection for user-provided fields.
        def safe(v):
            v=str(v or '')
            return "'"+v if v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
        stream=io.StringIO();writer=csv.writer(stream)
        writer.writerow(['ID','UTC date','Transaction','Gold','Silver','Copper','Copper total','Role','Guild member ID','Guild member','Purpose','Recorded by'])
        with connect() as db:
            for e in db.execute('SELECT * FROM treasury_ledger ORDER BY id ASC'):
                gld,rem=divmod(e['amount_copper'],10000);slv,cp=divmod(rem,100)
                writer.writerow([e['id'],e['created_at'],e['direction'],gld,slv,cp,e['amount_copper'],e['counterparty_role'],e['member_id'],safe(e['member_name']),safe(e['purpose']),e['recorded_by']])
        return Response(stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=critbot_treasury_ledger.csv','Cache-Control':'no-store'})
    return bp
