"""Simple member-to-member Request Board, with confirmation-based service credit.

Never assumes an item/gold moved in WoW. Only requesters confirm receipt; only
holders of treasury_manage can mark in-game guild bank supplies as provided.
"""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for
from .security import can
from .characters import owned
from .catalog import init_catalog, get_selected, search_page as catalog_search_page, stats as catalog_stats, PROFESSIONS
from .social import notify
import json

CATEGORIES=('Quest Help','Crafting','Materials','Help')
SERVICE_MILESTONES=((1,'First request completed'),(5,'Helping hand'),(10,'Reliable guildmate'),(25,'Guild artisan'),(50,'Community pillar'))


def init_requests(db):
    db.execute('''CREATE TABLE IF NOT EXISTS guild_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id TEXT NOT NULL,
        requester_character TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity BETWEEN 1 AND 999),
        details TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','claimed','delivered','completed','cancelled')),
        helper_id TEXT NOT NULL DEFAULT '',
        helper_character TEXT NOT NULL DEFAULT '',
        helper_note TEXT NOT NULL DEFAULT '',
        needs_guild_supplies INTEGER NOT NULL DEFAULT 0,
        supplies_status TEXT NOT NULL DEFAULT 'none' CHECK(supplies_status IN ('none','pending','provided','unavailable')),
        supplies_by TEXT NOT NULL DEFAULT '',
        supplies_note TEXT NOT NULL DEFAULT '',
        delivered_note TEXT NOT NULL DEFAULT '',
        receipt_note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        delivered_at TEXT,
        completed_at TEXT
    )''')
    for column,definition in (('catalog_key',"TEXT NOT NULL DEFAULT ''"),('catalog_snapshot',"TEXT NOT NULL DEFAULT ''"),('material_plan',"TEXT NOT NULL DEFAULT 'Discuss with helper'"),('offered_tip',"TEXT NOT NULL DEFAULT ''"),('meeting_zone',"TEXT NOT NULL DEFAULT ''"),('availability',"TEXT NOT NULL DEFAULT ''")):
        if column not in {r[1] for r in db.execute('PRAGMA table_info(guild_requests)')}:
            db.execute(f'ALTER TABLE guild_requests ADD COLUMN {column} {definition}')
    init_catalog(db)
    db.execute('CREATE INDEX IF NOT EXISTS ix_guild_requests_status ON guild_requests(status,created_at)')
    db.execute('CREATE INDEX IF NOT EXISTS ix_guild_requests_owner ON guild_requests(requester_id,status)')
    db.execute('CREATE INDEX IF NOT EXISTS ix_guild_requests_helper ON guild_requests(helper_id,status)')


def _record(db, order_id):
    order=db.execute('SELECT * FROM guild_requests WHERE id=?',(order_id,)).fetchone()
    if order is None: raise LookupError('Order not found.')
    return order


def _toon(db, mid, raw):
    if not raw: return ''
    try: ident=int(raw)
    except (ValueError, TypeError): raise ValueError('Choose a character from your own roster.')
    row=db.execute('SELECT name FROM member_characters WHERE id=? AND member_id=?',(ident,str(mid))).fetchone()
    if not row: raise ValueError('Choose a character from your own roster.')
    return row['name']


def _queue_existing_achievement(db, member_id, name):
    achievement=db.execute('SELECT id FROM achievements WHERE name=? COLLATE NOCASE',(name,)).fetchone()
    if not achievement:return
    aid=achievement['id']
    if db.execute('SELECT 1 FROM auto_deliveries WHERE achievement_id=? AND member_id=?',(aid,member_id)).fetchone():return
    owned=db.execute('SELECT 1 FROM unlocks WHERE achievement_id=? AND member_id=?',(aid,member_id)).fetchone()
    pending=db.execute('''SELECT id FROM award_queue WHERE achievement_id=? AND member_id=? AND status='pending' LIMIT 1''',(aid,member_id)).fetchone()
    # Reuse the bot's existing award queue. No unverified direct unlocks.
    queue_id = pending['id'] if pending else None
    if not owned and not pending:
        queue_id=db.execute('''INSERT INTO award_queue(achievement_id,member_id,action,detail)
             VALUES(?,?,'award',?)''',(aid,member_id,'Verified Request Board achievement')).lastrowid
    db.execute('''INSERT OR IGNORE INTO auto_deliveries(achievement_id,member_id,queue_id) VALUES(?,?,?)''',
               (aid,member_id,queue_id))


def _award_service(db, mid):
    unique=db.execute('''SELECT COUNT(DISTINCT requester_id) FROM guild_requests
        WHERE helper_id=? AND status='completed' ''',(mid,)).fetchone()[0]
    completed_crafts=db.execute('''SELECT COUNT(*) FROM guild_requests
        WHERE helper_id=? AND status='completed' AND category IN ('Crafting','Materials')''',(mid,)).fetchone()[0]
    if unique>=5:_queue_existing_achievement(db,mid,'Good Samaritan')
    if completed_crafts>=25:_queue_existing_achievement(db,mid,'Guild Quartermaster')


def create_order(db, member_id, category, title, quantity, details='', char_id='',catalog_key='',material_plan='Discuss with helper',offered_tip='',meeting_zone='',availability=''):
    if category not in CATEGORIES or len(details)>850:
        raise ValueError('Choose a request type and keep details under 850 characters.')
    entry=get_selected(db,category,catalog_key) if catalog_key else None
    if entry:
        title=(entry['item_made'] or entry['name']) if category=='Crafting' else entry['name']
        if category=='Quest Help':quantity=1
    if not 3<=len(title.strip())<=90:
        raise ValueError('Choose a catalog result or enter a title between 3 and 90 characters.')
    try: qty=int(quantity)
    except (ValueError,TypeError): raise ValueError('Quantity must be a whole number.')
    if not 1<=qty<=999:raise ValueError('Quantity must be between 1 and 999.')
    member_id=str(member_id)
    if db.execute("SELECT COUNT(*) FROM guild_requests WHERE requester_id=? AND status IN ('open','claimed','delivered')",(member_id,)).fetchone()[0]>=10:
        raise ValueError('Finish your existing requests before opening more than ten.')
    if material_plan not in ('Discuss with helper','I have materials','Need materials','Ask guild for supplies'):
        raise ValueError('Choose a valid materials preference.')
    if category == 'Quest Help':
        qty = 1  # Quest help is an activity, not a quantity of goods.
        material_plan, offered_tip = 'Not applicable', ''
    meeting_zone, availability = meeting_zone.strip()[:90], availability.strip()[:110]
    if len(offered_tip)>35 or any(c in offered_tip for c in '<>\n\r'):
        raise ValueError('Keep the offered tip short and plain text.')
    toon=_toon(db,member_id,char_id)
    snapshot=json.dumps({k:entry[k] for k in ('kind','name','zone','quest_giver','faction','quest_level','objectives','requirements','profession','item_made','materials','skill_range','source_url','data_status')},ensure_ascii=False) if entry else ''
    return db.execute('''INSERT INTO guild_requests(requester_id,requester_character,category,title,quantity,details,catalog_key,catalog_snapshot,material_plan,offered_tip,meeting_zone,availability)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(member_id,toon,category,title.strip(),qty,details.strip(),catalog_key,snapshot,material_plan,offered_tip.strip(),meeting_zone,availability)).lastrowid


def take_action(db, order_id, member_id, action, form, treasurer=False):
    mid=str(member_id)
    db.execute('BEGIN IMMEDIATE')
    order=_record(db,order_id)
    status=order['status']
    note=form.get('note','').strip()
    if len(note)>500:raise ValueError('Keep notes under 500 characters.')
    if action=='claim':
        if mid==order['requester_id']:raise ValueError('You cannot fulfill your own request.')
        if status!='open':raise ValueError('That request has already been claimed or closed.')
        toon=_toon(db,mid,form.get('character_id',''))
        needs=form.get('guild_supplies')=='yes' and order['category'] in ('Crafting','Materials')
        db.execute('''UPDATE guild_requests SET helper_id=?,helper_character=?,helper_note=?,
              status='claimed',needs_guild_supplies=?,supplies_status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?''',
              (mid,toon,note,int(needs),'pending' if needs else 'none',order_id))
        notify(db,order['requester_id'],mid,'request','A guildmate claimed your request',f"{order['title']} is being handled.",'/hub/requests#my-requests')
    elif action=='release':
        if status!='claimed' or order['helper_id']!=mid:raise ValueError('Only the assigned helper can release this claim.')
        db.execute('''UPDATE guild_requests SET helper_id='',helper_character='',helper_note='',
            needs_guild_supplies=0,supplies_status='none',supplies_by='',supplies_note='',
            status='open',updated_at=CURRENT_TIMESTAMP WHERE id=?''',(order_id,))
        notify(db,order['requester_id'],mid,'request','Your request is open again',f"{order['title']} needs another helper.",'/hub/requests#my-requests')
    elif action=='delivered':
        if status!='claimed' or order['helper_id']!=mid:raise ValueError('Only the assigned helper can mark this delivered.')
        if order['needs_guild_supplies'] and order['supplies_status']!='provided':
            raise ValueError('Guild supplies must be confirmed first, or release the request and reclaim using your own materials.')
        db.execute('''UPDATE guild_requests SET status='delivered',delivered_note=?,delivered_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP WHERE id=?''',(note,order_id))
        notify(db,order['requester_id'],mid,'request',
             'Confirm your quest help' if order['category']=='Quest Help' else 'Confirm your delivery',
             f"{order['title']} was marked complete by your helper. Confirm once your quest help is finished." if order['category']=='Quest Help' else f"{order['title']} was marked delivered. Check it in game, then confirm receipt.",'/hub/requests#my-requests')
    elif action=='confirm':
        if status!='delivered' or order['requester_id']!=mid:raise ValueError('Only the requester can confirm delivery.')
        db.execute('''UPDATE guild_requests SET status='completed',receipt_note=?,completed_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP WHERE id=?''',(note,order_id))
        _award_service(db,order['helper_id'])
        notify(db,order['helper_id'],mid,'request','Your help was confirmed',f"{order['title']} was confirmed complete. Guild service credit recorded.",'/hub/requests#my-requests')
    elif action=='cancel':
        if order['requester_id']!=mid or status!='open':raise ValueError('Only an unclaimed request can be cancelled.')
        db.execute("UPDATE guild_requests SET status='cancelled',updated_at=CURRENT_TIMESTAMP WHERE id=?",(order_id,))
    elif action in ('supplied','unavailable'):
        if not treasurer:raise PermissionError('Treasury access required.')
        if status!='claimed' or not order['needs_guild_supplies'] or order['supplies_status']!='pending':
            raise ValueError('This request is not awaiting guild supplies.')
        db.execute('''UPDATE guild_requests SET supplies_status=?,supplies_by=?,supplies_note=?,
              updated_at=CURRENT_TIMESTAMP WHERE id=?''',
              ('provided' if action=='supplied' else 'unavailable',mid,note,order_id))
        notify(db,order['helper_id'],mid,'request','Guild supplies updated',f"Supplies for {order['title']} were marked {'provided' if action=='supplied' else 'unavailable'}.",'/hub/requests#my-requests')
    else: raise ValueError('Unknown request action.')


def blueprint(connect):
    bp=Blueprint('requests',__name__)

    @bp.get('/hub/requests')
    def board():
        mid=g.dashboard_access['discord_id']
        category=request.args.get('category','All')
        if category not in ('All',*CATEGORIES):category='All'
        with connect() as db:
            sql="""SELECT r.*,a.display_name requester_name,b.display_name helper_name
                  FROM guild_requests r
                  LEFT JOIN member_directory a ON a.member_id=r.requester_id
                  LEFT JOIN member_directory b ON b.member_id=r.helper_id"""
            all_orders=[dict(r) for r in db.execute(sql+' ORDER BY r.id DESC LIMIT 250')]
            for entry in all_orders:
                try:entry['catalog']=json.loads(entry.get('catalog_snapshot','')) if entry.get('catalog_snapshot') else {}
                except (ValueError,TypeError):entry['catalog']={}
            my_characters=owned(db,mid)
            total=db.execute("SELECT COUNT(*) FROM guild_requests WHERE helper_id=? AND status='completed'",(mid,)).fetchone()[0]
        open_orders=[o for o in all_orders if o['status']=='open' and (category=='All' or o['category']==category)]
        my_orders=[o for o in all_orders if (o['requester_id']==mid or o['helper_id']==mid) and o['status'] not in ('cancelled',)]
        pending=[o for o in all_orders if o['status']=='claimed' and o['needs_guild_supplies'] and o['supplies_status']=='pending']
        is_treasurer=can(g.dashboard_access,'treasury_manage')
        next_goal=next(((n,label) for n,label in SERVICE_MILESTONES if n>total),None)
        with connect() as db:catalog_overview=catalog_stats(db)
        return render_template('hub_requests.html',categories=CATEGORIES,category=category,
            open_orders=open_orders,my_orders=my_orders,needs_supplies=pending if is_treasurer else [],
            characters=my_characters,completed=total,next_goal=next_goal,treasurer=is_treasurer,professions=PROFESSIONS,catalog_overview=catalog_overview)

    @bp.get('/hub/catalog/search')
    def find_catalog_entries():
        kind=request.args.get('kind','quest')
        if kind not in ('quest','craft','material'):abort(400)
        try:
            page=int(request.args.get('page','1'))
        except (TypeError,ValueError):page=1
        with connect() as db:
            result=catalog_search_page(db,kind,request.args.get('q',''),request.args.get('profession',''),request.args.get('zone',''),page,6,request.args.get('faction','all'))
            totals=catalog_stats(db)['counts']
        return jsonify({**result,'total_available':totals.get(kind,0),'kind':kind,
            'coverage':'Community-sourced; live game availability is not guaranteed.'})

    @bp.post('/hub/requests/new')
    def new():
        mid=g.dashboard_access['discord_id']
        try:
            with connect() as db:
                create_order(db,mid,request.form.get('category',''),request.form.get('title',''),
                            request.form.get('quantity','1'),request.form.get('details',''),request.form.get('character_id',''),request.form.get('catalog_key',''),request.form.get('material_plan','Discuss with helper'),request.form.get('offered_tip',''),request.form.get('meeting_zone',''),request.form.get('availability',''))
            flash('Your request is on the board. Guildmates can now claim it.','success')
        except ValueError as exc:flash(str(exc),'error')
        return redirect(url_for('hub.home') if request.form.get('origin')=='hub' else url_for('requests.board'))

    @bp.post('/hub/requests/<int:order_id>/<action>')
    def action(order_id,action):
        mid=g.dashboard_access['discord_id']
        if action not in ('claim','release','delivered','confirm','cancel','supplied','unavailable'):abort(404)
        try:
            with connect() as db:
                take_action(db,order_id,mid,action,request.form,treasurer=can(g.dashboard_access,'treasury_manage'))
            flash({'claim':'Request claimed!','release':'Claim released.','delivered':'Marked delivered. Awaiting requester confirmation.',
                   'confirm':'Receipt confirmed. Service credit recorded.','cancel':'Request cancelled.',
                   'supplied':'Guild supplies marked as provided.','unavailable':'Supply request marked unavailable.'}[action],'success')
        except LookupError:abort(404)
        except PermissionError:abort(403)
        except ValueError as exc:flash(str(exc),'error')
        return redirect(url_for('hub.home') if request.form.get('origin')=='hub' else url_for('requests.board'))

    return bp
