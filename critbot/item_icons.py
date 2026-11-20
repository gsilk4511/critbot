"""WoW: Forever item artwork and cached tooltip details.

The game item ID is the join key, never a fuzzy item-name guess.  Artwork is
looked up against the community Forever cache.  Missing/unverified artwork
stays a question-mark rather than falsely representing another item.

No remote calls in a web request: metadata is prepared by SYNC_ITEM_ICONS.py.
"""
import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / 'static' / 'item-icons'
MANIFEST = ASSET_DIR / 'manifest.json'
TOOLTIPS = ASSET_DIR / 'item-tooltips.json.gz'
FALLBACK_QUALITY = Path(__file__).with_name('foreverguide_item_quality.json.gz')
CACHE = {}
CDN = 'https://wow.zamimg.com/images/wow/icons/large/'
ICON_RE = re.compile(r'^[a-z0-9_]{1,100}$')


def _load(path, gzip_file=False):
    key = str(path)
    try:
        mtime = path.stat().st_mtime_ns
        saved = CACHE.get(key)
        if saved and saved[0] == mtime:
            return saved[1]
        with (gzip.open(path, 'rt', encoding='utf-8') if gzip_file else path.open('r', encoding='utf-8')) as fh:
            obj = json.load(fh)
        if not isinstance(obj, dict):
            obj = {}
        CACHE[key] = (mtime, obj)
        return obj
    except (OSError, ValueError, TypeError):
        return {}


def manifest():
    return _load(MANIFEST)


def tooltip_data(item_id):
    if item_id is None or str(item_id) in ('', 'None', '0'):
        return {}
    data = _load(TOOLTIPS, gzip_file=True).get(str(item_id), {})
    if isinstance(data, list):
        return {'lines': data, 'source': 'Forever item cache (legacy)'}
    return data if isinstance(data, dict) else {}


def _icon_for(item_id):
    raw = manifest().get(str(item_id)) if item_id is not None else None
    if isinstance(raw, dict):
        raw = raw.get('icon')
    if not isinstance(raw, str) or not ICON_RE.fullmatch(raw):
        return None, None
    local_path = ASSET_DIR / (raw + '.jpg')
    return raw, ('/static/item-icons/' + raw + '.jpg' if local_path.exists() else CDN + raw + '.jpg')


def _fallback_category(name, profession=''):
    name = str(name or '').lower()
    patterns = [
      ('bag', ('bag','satchel','knapsack','pouch','pack')),
      ('cloth', ('cloth','bolt of','fabric','linen','wool','silk','mageweave','runecloth')),
      ('thread', ('thread','twine','string')),
      ('ore', ('ore','mineral','coal','stone','rock','granite','rock salt')),
      ('bar', ('bar','ingot','rod','alloy','bronze','steel')),
      ('leather', ('leather','hide','scale','skin','rugged')),
      ('herb', ('herb','leaf','root','weed','flower','bloom','moss','lotus','thorn','foil','briarthorn')),
      ('potion', ('potion','mana','healthstone','draught')),
      ('elixir', ('elixir','flask','tonic','oil')),
      ('food', ('bread','meat','pie','cake','stew','spice','sausage','roast','soup','cheese','egg','rum')),
      ('fish', ('fish','snapper','salmon','catfish','trout','eel')),
      ('gem', ('gem','ruby','sapphire','diamond','pearl','agate','jade','topaz','citrine','emerald')),
      ('dust', ('dust','essence','shard','crystal','powder')),
      ('enchant', ('enchant','enchantment','enchanted','glowing')),
      ('scroll', ('scroll','parchment','pattern','recipe','formula','schematic','plans')),
      ('shield', ('shield','buckler')),
      ('weapon', ('sword','mace','axe','dagger','bow','staff','wand','spear','knife','arrow','bullet')),
      ('armor', ('helmet','helm','bracer','chest','robe','gloves','belt','boot','pants','shoulder','mail','plate','cloak','tunic','vest')),
      ('jewel', ('ring','necklace','pendant','trinket','amulet')),
      ('tool', ('hammer','wrench','grinder','anvil','engineering')),
      ('bandage', ('bandage','antidote','healing salve')),
    ]
    for category,words in patterns:
        if any(word in name for word in words):return category
    default={'Tailoring':'cloth','Blacksmithing':'weapon','Enchanting':'enchant',
             'Alchemy':'potion','Engineering':'tool','Leatherworking':'leather',
             'Cooking':'food','First Aid':'bandage','Jewelcrafting':'jewel',
             'Mining':'ore','Herbalism':'herb','Fishing':'fish'}
    return default.get(profession,'misc')


def _fallback_metadata(record):
    category = _fallback_category(record.get('name'),record.get('profession'))
    record['icon_fallback_url'] = '/static/item-fallbacks/' + category + '.png'
    record['icon_fallback_category'] = category
    return record


def _decorate_item(record, item_id):
    record['item_id'] = item_id
    _fallback_metadata(record)
    icon_name, icon_url = _icon_for(item_id)
    if icon_url:
        record['icon_name'] = icon_name
        record['icon_url'] = icon_url
        record['icon_verified'] = True
    else:
        record['icon_verified'] = False
    tooltip = tooltip_data(item_id)
    record['wow_tooltip'] = tooltip
    record['tooltip_lines'] = tooltip.get('lines', [])
    quality_reference = _load(FALLBACK_QUALITY, gzip_file=True).get(str(item_id), {})
    record['quality'] = tooltip.get('quality') if tooltip.get('quality') is not None else quality_reference.get('quality')
    record['item_description'] = tooltip.get('description') or ''
    record['item_level'] = tooltip.get('item_level') if tooltip.get('item_level') is not None else quality_reference.get('item_level')
    return record


def enrich(record):
    kind = record.get('kind')
    if kind == 'craft':
        item_id = record.get('output_item_id')
    elif kind == 'material':
        item_id = record.get('item_id')
    else:
        item_id = None
    if item_id:
        _decorate_item(record, item_id)
    elif kind == 'craft':
        record['item_id'] = None
        record['icon_verified'] = False
        _fallback_metadata(record)
        record['wow_tooltip'] = {}
        record['tooltip_lines'] = []

    if kind == 'craft' and record.get('metadata_json'):
        try:
            meta = json.loads(record['metadata_json'])
            record['produces_quantity'] = meta.get('produces_quantity', 1)
            record['learn_skill'] = meta.get('learn_skill')
            record['trainer_taught'] = meta.get('trainer_taught')
            reagents = []
            for material in (meta.get('reagents') or [])[:40]:
                reagent = {
                    'kind': 'material',
                    'name': str(material.get('name') or 'Unknown material')[:150],
                    'qty': material.get('qty', 1),
                    'profession': record.get('profession', ''),
                }
                _decorate_item(reagent, material.get('item_id'))
                reagents.append(reagent)
            record['reagents'] = reagents
        except (ValueError, TypeError, KeyError):
            record['reagents'] = []
    return record
