"""Versioned WoW: Forever catalogs for the Request Board.

Source data always carries provenance. Unknown quest givers/requirements stay blank.
Adds only catalog tables to the existing SQLite DB; no live network calls.
"""
from __future__ import annotations
import json, sqlite3, re, gzip
from .item_icons import enrich
from pathlib import Path

PROFESSIONS=(
    'Alchemy','Blacksmithing','Enchanting','Engineering','Leatherworking','Tailoring',
    'Cooking','First Aid','Mining','Herbalism','Skinning','Fishing',
    'Poisons','Lockpicking','Comprehension','Riding'
)
SEED_PATH=Path(__file__).with_name('catalog_seed.json')
BUNDLED_GUIDE=Path(__file__).with_name('foreverguide_catalog.json.gz')
GUIDE_SOURCE='ForeverGuide_1.39.5_reference_catalog'
EXTRA_COLS={'quest_id':'INTEGER','recipe_spell_id':'INTEGER','output_item_id':'INTEGER','giver_npc_id':'INTEGER','map_id':'INTEGER','coord_x':'TEXT','coord_y':'TEXT','metadata_json':'TEXT'}


def init_catalog(db):
    db.execute('''CREATE TABLE IF NOT EXISTS forever_catalog (
        catalog_key TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK(kind IN ('quest','craft')),
        name TEXT NOT NULL,
        profession TEXT NOT NULL DEFAULT '',
        zone TEXT NOT NULL DEFAULT '',
        quest_giver TEXT NOT NULL DEFAULT '',
        faction TEXT NOT NULL DEFAULT 'Unverified',
        quest_level TEXT NOT NULL DEFAULT '',
        objectives TEXT NOT NULL DEFAULT '',
        requirements TEXT NOT NULL DEFAULT '',
        materials TEXT NOT NULL DEFAULT '',
        item_made TEXT NOT NULL DEFAULT '',
        skill_range TEXT NOT NULL DEFAULT '',
        recipe_type TEXT NOT NULL DEFAULT '',
        new_in_forever INTEGER NOT NULL DEFAULT 0,
        data_status TEXT NOT NULL DEFAULT 'partial',
        source_url TEXT NOT NULL DEFAULT '',
        source_build TEXT NOT NULL DEFAULT '',
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS ix_forever_catalog_kind_prof ON forever_catalog(kind,profession)')
    db.execute('CREATE INDEX IF NOT EXISTS ix_forever_catalog_name ON forever_catalog(name COLLATE NOCASE)')
    db.execute('CREATE INDEX IF NOT EXISTS ix_forever_catalog_zone ON forever_catalog(zone COLLATE NOCASE)')
    db.execute('CREATE INDEX IF NOT EXISTS ix_forever_catalog_faction ON forever_catalog(kind,faction,quest_level)')
    db.execute('''CREATE TABLE IF NOT EXISTS forever_material_index (
        name TEXT PRIMARY KEY, used_by TEXT NOT NULL DEFAULT '', recipe_uses INTEGER NOT NULL DEFAULT 0, item_id INTEGER
    )''')
    if 'item_id' not in {r[1] for r in db.execute('PRAGMA table_info(forever_material_index)')}:
        db.execute('ALTER TABLE forever_material_index ADD COLUMN item_id INTEGER')
    db.execute('''CREATE TABLE IF NOT EXISTS forever_catalog_imports (
        source_name TEXT PRIMARY KEY, item_count INTEGER NOT NULL,
        status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    # Stable quest/spell/item/NPC IDs permit precise catalog lookups.
    existing_cols={r[1] for r in db.execute('PRAGMA table_info(forever_catalog)')}
    for col,typ in EXTRA_COLS.items():
        if col not in existing_cols:
            db.execute(f'ALTER TABLE forever_catalog ADD COLUMN {col} {typ}')
    db.execute('CREATE INDEX IF NOT EXISTS ix_forever_catalog_output_item ON forever_catalog(output_item_id)')
    db.execute('CREATE INDEX IF NOT EXISTS ix_forever_catalog_quest_id ON forever_catalog(quest_id)')
    # Only initialize a small, explicitly sourced starter set. Never overwrite a synced catalog.
    current=db.execute('SELECT COUNT(*) FROM forever_catalog').fetchone()[0]
    if current == 0 and not BUNDLED_GUIDE.exists() and SEED_PATH.exists():
        data=json.loads(SEED_PATH.read_text(encoding='utf-8'))
        upsert_catalog(db,data.get('quests',[])+data.get('recipes',[]))
        db.execute('''INSERT OR REPLACE INTO forever_catalog_imports
            (source_name,item_count,status,note) VALUES(?,?,?,?)''',
            ('starter_sample',len(data.get('quests',[]))+len(data.get('recipes',[])),
             'partial','Small verified sample; first launch attempts to import larger public-source catalogs.'))
    import_bundled_guide(db)
    if db.execute('SELECT COUNT(*) FROM forever_material_index').fetchone()[0]==0 or (
        db.execute('SELECT COUNT(*) FROM forever_material_index WHERE item_id IS NOT NULL').fetchone()[0]==0
        and db.execute("SELECT COUNT(*) FROM forever_catalog WHERE kind='craft' AND metadata_json IS NOT NULL").fetchone()[0]>0):
        rebuild_material_index(db)

COLUMNS=('catalog_key','kind','name','profession','zone','quest_giver','faction','quest_level','objectives',
         'requirements','materials','item_made','skill_range','recipe_type','new_in_forever',
         'data_status','source_url','source_build','quest_id','recipe_spell_id','output_item_id','giver_npc_id','map_id','coord_x','coord_y','metadata_json')

def upsert_catalog(db,entries):
    sql=(f"INSERT INTO forever_catalog({','.join(COLUMNS)}) VALUES({','.join('?' for _ in COLUMNS)}) "
         'ON CONFLICT(catalog_key) DO UPDATE SET '+','.join(f'{col}=excluded.{col}' for col in COLUMNS if col != 'catalog_key'))
    n=0
    for entry in entries:
        if not isinstance(entry,dict) or not entry.get('catalog_key') or not entry.get('name'):continue
        if entry.get('kind') not in ('quest','craft'):continue
        db.execute(sql,tuple(entry.get(c,0 if c=='new_in_forever' else '' if c=='metadata_json' else None if c in EXTRA_COLS else '') for c in COLUMNS))
        n+=1
    return n

def import_bundled_guide(db):
    """Install bundled game catalog records once per database."""
    if not BUNDLED_GUIDE.exists():return 0
    if db.execute('SELECT 1 FROM forever_catalog_imports WHERE source_name=?',(GUIDE_SOURCE,)).fetchone():return 0
    with gzip.open(BUNDLED_GUIDE,'rt',encoding='utf-8') as fh:
        payload=json.load(fh)
    quests=payload.get('quests',[]);crafts=payload.get('recipes',[])
    if len(quests)<1500 or len(crafts)<2000:
        raise ValueError('Refusing incomplete bundled ForeverGuide catalog.')
    db.execute('SAVEPOINT install_guide_catalog')
    try:
        db.execute("DELETE FROM forever_catalog WHERE catalog_key LIKE 'quest:sample:%' OR catalog_key LIKE 'craft:sample:%'")
        installed=upsert_catalog(db,quests+crafts)
        rebuild_material_index(db)
        db.execute('''INSERT INTO forever_catalog_imports(source_name,item_count,status,note)
          VALUES(?,?,?,?)''',(GUIDE_SOURCE,installed,'GAME DATA / LIVE UNVERIFIED',
            'All parsed Horde/uncertain quests and recipe spells from user-supplied ForeverGuide 1.39.5. Not proof of all live game records.'))
        db.execute('RELEASE SAVEPOINT install_guide_catalog')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT install_guide_catalog')
        db.execute('RELEASE SAVEPOINT install_guide_catalog')
        raise
    return installed

def rebuild_material_index(db):
    # Materials are derived from recipe reagents, not blindly copied item names.
    all_mat={}
    for materials,profession,metadata_json in db.execute("SELECT materials,profession,metadata_json FROM forever_catalog WHERE kind='craft'"):
        try: reagents=json.loads(metadata_json or '{}').get('reagents',[])
        except (TypeError,ValueError): reagents=[]
        id_by_name={r.get('name','').casefold():r.get('item_id') for r in reagents}
        for token in (materials or '').split(','):
            piece=token.strip()
            piece=re.sub(r'^\d+\s*[×x]\s*','',piece)
            piece=re.sub(r'^\d+\s+','',piece)
            if not piece or len(piece)>90 or piece.lower().startswith(('unknown','not verified','+','more ')):
                continue
            k=piece.casefold()
            item=all_mat.setdefault(k,{'name':piece,'professions':set(),'count':0,'item_id':id_by_name.get(k)})
            if profession:item['professions'].add(profession)
            item['count']+=1
    db.execute('DELETE FROM forever_material_index')
    db.executemany('INSERT INTO forever_material_index(name,used_by,recipe_uses,item_id) VALUES(?,?,?,?)',
       [(v['name'],', '.join(sorted(v['professions'])),v['count'],v['item_id']) for v in all_mat.values()])
    return len(all_mat)

def _like(text):
    return text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')


def _filters(kind='quest',term='',profession='',zone='',faction='eligible'):
    # One filter for both results and total counts, with parameterized SQL.
    if kind not in ('quest','craft'):
        raise ValueError('Invalid catalog type')
    where=['kind=?'];args=[kind]
    if kind=='quest':
        if faction=='verified':
            where.append("faction='Horde'")
        elif faction=='eligible':
            where.append("faction IN ('Horde','Neutral / verify','Neutral','Both')")
        elif faction=='unknown':
            where.append("faction IN ('Unverified','')")
        else:
            where.append("faction!='Alliance'")
        if zone:
            where.append("zone LIKE ? ESCAPE '\\'")
            args.append('%'+_like(zone.strip()[:70])+'%')
    elif profession and profession in PROFESSIONS:
        where.append('profession=?');args.append(profession)
    if term:
        like='%'+_like(term.strip()[:120])+'%'
        fields=('name','zone','quest_giver','objectives','requirements','catalog_key') if kind=='quest' else ('name','profession','materials','item_made','recipe_type','catalog_key')
        where.append('('+ ' OR '.join(f"{f} LIKE ? ESCAPE '\\'" for f in fields)+')')
        args.extend([like]*len(fields))
    return ' AND '.join(where),args


def material_page(db,term='',profession='',page=1,page_size=8):
    page=max(1,min(int(page),100000));page_size=max(1,min(int(page_size),40))
    args=[];where=['1=1']
    if profession and profession in PROFESSIONS:
        where.append("used_by LIKE ? ESCAPE '\\'");args.append('%'+_like(profession)+'%')
    if term:
        like='%'+_like(term.strip()[:120])+'%'
        where.append("(name LIKE ? ESCAPE '\\' OR used_by LIKE ? ESCAPE '\\')");args.extend([like,like])
    predicate=' AND '.join(where)
    total=db.execute('SELECT COUNT(*) FROM forever_material_index WHERE '+predicate,args).fetchone()[0]
    pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    rows=db.execute('SELECT * FROM forever_material_index WHERE '+predicate+' ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?',args+[page_size,(page-1)*page_size])
    return {'records':[enrich({'catalog_key':'','kind':'material','name':r['name'],'profession':r['used_by'],'recipe_uses':r['recipe_uses'],'item_id':r['item_id'],'materials':'','source_url':'','data_status':'Derived from imported recipe reagents'}) for r in rows],
            'total':total,'page':page,'pages':pages,'page_size':page_size}

def search_page(db,kind='quest',term='',profession='',zone='',page=1,page_size=16,faction='eligible'):
    # Pages through all locally imported entries, not just the first 60 matches.
    if kind=='material':return material_page(db,term,profession,page,page_size)
    page=max(1,min(int(page),100000));page_size=max(1,min(int(page_size),40))
    where,args=_filters(kind,term,profession,zone,faction)
    total=db.execute('SELECT COUNT(*) FROM forever_catalog WHERE '+where,args).fetchone()[0]
    pages=max(1,(total+page_size-1)//page_size)
    page=min(page,pages)
    order=" ORDER BY CASE WHEN name LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END, name COLLATE NOCASE, catalog_key LIMIT ? OFFSET ?"
    rows=db.execute('SELECT * FROM forever_catalog WHERE '+where+order,
      args+[_like((term or '').strip()[:120])+'%',page_size,(page-1)*page_size])
    return {'records':[enrich(dict(row)) for row in rows],'total':total,'page':page,'pages':pages,'page_size':page_size}


def search(db,kind='quest',term='',profession='',zone='',limit=30):
    # Compatibility for old self-tests and legacy clients.
    return search_page(db,kind,term,profession,zone,1,limit,'all')['records']

def stats(db):
    rows=db.execute('SELECT kind,COUNT(*) FROM forever_catalog GROUP BY kind').fetchall()
    sources=db.execute('SELECT source_name,item_count,status,note,imported_at FROM forever_catalog_imports ORDER BY imported_at DESC').fetchall()
    counts={row[0]:row[1] for row in rows}
    counts['material']=db.execute('SELECT COUNT(*) FROM forever_material_index').fetchone()[0]
    return {'counts':counts,'imports':[dict(x) for x in sources]}

def get_selected(db,category,key):
    if not key:return None
    expected='quest' if category=='Quest Help' else 'craft' if category=='Crafting' else None
    if not expected: raise ValueError('This request type does not use the quest or crafting catalog.')
    row=db.execute('SELECT * FROM forever_catalog WHERE catalog_key=? AND kind=?',(key,expected)).fetchone()
    if row is None:raise ValueError('The selected catalog entry no longer exists. Please search again.')
    return dict(row)
