"""Approved visual presets for safe, user-personalized member pages.
No user-supplied CSS, HTML, or arbitrary image URLs are accepted.
"""
import json
THEMES={
 'ember':'Ember & gold','crimson':'Crimson oath','frost':'Frostbound','arcane':'Arcane glow',
 'verdant':'Wildheart','shadow':'Shadowforge','royal':'Royal sapphire','silver':'Silver sentinel',
 'sunset':'Sundown copper','ocean':'Deep sea','amethyst':'Amethyst dusk','sand':'Desert gold',
 'rose':'Roseguard','night':'Midnight blue','jade':'Ancient jade','whitegold':'Ivory & gold'}
BANNERS={'flare':'Flame-lit (color only)','runes':'Runic circles (color only)',
 'diagonal':'War banners (color only)','minimal':'Minimal (color only)',
 'ashen-citadel':'Ashen Citadel • original artwork','moonveil-keep':'Moonveil Keep • original artwork',
 'frostfall-peaks':'Frostfall Peaks • original artwork','wildwood-canopy':'Wildwood Canopy • original artwork',
 'arcane-observatory':'Arcane Observatory • original artwork','stormglass-coast':'Stormglass Coast • original artwork',
 'desert-bastion':'Desert Bastion • original artwork','crimson-spire':'Crimson Spire • original artwork',
 'twilight-marsh':'Twilight Marsh • original artwork','dawnwatch-city':'Dawnwatch City • original artwork',
 'starlit-temple':'Starlit Temple • original artwork','emerald-hollows':'Emerald Hollows • original artwork'}
LAYOUTS={'story':'Balanced (story + trophies)','showcase':'Trophies first','compact':'Minimal single column','wide':'Wide cinematic','chronicle':'Journal / chronicle','spotlight':'Achievement spotlight'}
AWARD_VIEWS={'featured':'Hero spotlight','gallery':'Card gallery','minimal':'Compact list','medals':'Medal collection','timeline':'Achievement timeline'}
FRAMES={'ornate':'Royal ornate','rune':'Runic etched','sleek':'Minimal clean','crystal':'Crystal facets','forged':'Forged steel','thorn':'Thornbound','sun':'Sunforged','shadow':'Midnight'}
TYPOGRAPHY={'classic':'Classic fantasy','modern':'Modern sharp','banner':'Banner capitals','literary':'Chronicle serif'}
ART_FILTERS={'balanced':'Balanced color','vivid':'Vivid & luminous','muted':'Soft muted','noir':'Moody noir'}
AVATARS={'monogram':'Initial crest','circle':'Round seal','diamond':'Cut diamond','plain':'Clean square'}
TROPHY_DENSITY={'balanced':'Balanced awards','roomy':'Large awards','compact':'Compact awards'}
ART_BANNERS={k:v for k,v in BANNERS.items() if k not in {'flare','runes','diagonal','minimal'}}
def profile_defaults():
    return dict(about='',main_character='',main_class='',interests='',availability='',goals='',
        staff_status='No designation',staff_department='',staff_notes='',updated_at=None,staff_updated_at=None,
        tagline='',theme='ember',banner='flare',layout='story',award_view='featured',frame_style='ornate',
        typography='classic',art_filter='balanced',avatar_style='monogram',trophy_density='balanced',portrait='none',portrait_emblem='none',
        showcase_caption='',featured_achievements='[]',achievement_captions='{}')
def read_showcase(profile, collection):
    owned={int(a['id']) for a in collection}
    try:ids=json.loads(profile.get('featured_achievements') or '[]')
    except (ValueError,TypeError):ids=[]
    if not isinstance(ids,list):ids=[]
    featured=[]
    for raw in ids:
        if isinstance(raw,int) and raw in owned and raw not in featured:featured.append(raw)
    try:captions=json.loads(profile.get('achievement_captions') or '{}')
    except (ValueError,TypeError):captions={}
    if not isinstance(captions,dict):captions={}
    captions={str(k):v[:65] for k,v in captions.items() if str(k).isdigit() and int(k) in featured and isinstance(v,str)}
    return featured[:3],captions

# Curated original fantasy artwork, bundled locally. No arbitrary URL or file inputs.
# The portrait picker is deliberately separate from page-layout controls.
PORTRAIT_GROUPS = {
    'all': 'All portraits', 'heroes': 'Heroes & warriors',
    'arcane': 'Magic & mystery', 'creatures': 'Creatures & legends'
}
PORTRAITS = {}
for series, count in ((1,21), (2,16), (3,20)):
    for index in range(1,count+1):
        key=f'portrait-{series}-{index:02d}'
        # These are visual-library groupings; no claims about canonical game species.
        group=('heroes','arcane','creatures')[(index+series)%3]
        PORTRAITS[key]={'label':f'Fantasy portrait {len(PORTRAITS)+1:02d}', 'group':group,
                        'file':f'profile-portraits/{key}.webp'}
EMBLEMS={'none': {'label':'No emblem','file':None}}
EMBLEM_NAMES = (
    'Lionheart','Battle Standard','Crossed Blades','Guardian Shield','Spellbook',
    'Runeblade','War Hammer','Tracker','Archer','Potion Keeper',
    'Skull Guard','Iron Gear','Crescent','Sunburst','Ancient Grove',
    'Inferno','Frost Sigil','Arcane Spiral','Dragon Crest','Tavern Legend'
)
for index,label in enumerate(EMBLEM_NAMES,1):
    EMBLEMS[f'emblem-{index:02d}']={'label':label,'file':f'profile-portraits/emblem-{index:02d}.webp'}

# Surface six high-quality starting points; retain legacy choices in the data model so
# existing profiles don't break, but don't overwhelm members with the old library.
STUDIO_BANNERS={key:BANNERS[key] for key in ('flare','minimal','ashen-citadel','moonveil-keep','frostfall-peaks','arcane-observatory')}
STUDIO_MAIN_THEMES={key:THEMES[key] for key in ('ember','frost','arcane','verdant','shadow','royal')}
STUDIO_OTHER_THEMES={key:value for key,value in THEMES.items() if key not in STUDIO_MAIN_THEMES}
