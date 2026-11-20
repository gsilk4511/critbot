"""Dynamic unlock-card renderer. Exact data stays in code; artwork is bundled."""
import hashlib
import io
import random
import math
from functools import lru_cache
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from .paths import ROOT

SIZE = (1200,640)
STYLES = {
    'Common': ('#bcc3ce', 155, 1, 0),
    'Uncommon': ('#7bd39a', 132, 2, 5),
    'Rare': ('#76bcff', 105, 2, 12),
    'Epic': ('#c397ff', 65, 2, 24),
    'Legendary': ('#f4c66c', 16, 3, 42),
    'Mythic': ('#f195bb', 10, 3, 42),
}

@lru_cache(maxsize=160)
def font(size,kind='sans'):
    names={'sans':'DejaVuSans.ttf','bold':'DejaVuSans-Bold.ttf','serif':'DejaVuSerif-Bold.ttf'}
    # Linux deployments use system fonts; no bundled font redistribution.
    family = 'DejaVuSerif-Bold.ttf' if kind == 'serif' else ('DejaVuSans-Bold.ttf' if kind == 'bold' else 'DejaVuSans.ttf')
    for path in (f'/usr/share/fonts/truetype/dejavu/{family}', family):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)

def clean(value,limit):
    return ' '.join(str(value or '').split())[:limit]

def lines_for(draw,text,typeface,width):
    lines=[];line=''
    for word in text.split():
        if draw.textlength(word,font=typeface)>width:
            pieces=[];piece=''
            for char in word:
                if piece and draw.textlength(piece+char,font=typeface)>width:
                    pieces.append(piece);piece=''
                piece+=char
            if piece:pieces.append(piece)
        else:pieces=[word]
        for part in pieces:
            candidate=(line+' '+part).strip()
            if line and draw.textlength(candidate,font=typeface)>width:
                lines.append(line);line=part
            else:line=candidate
    if line:lines.append(line)
    return lines or ['']

def title_layout(draw,text,width=690,height=145):
    for size in range(56,21,-2):
        typeface=font(size,'serif');lines=lines_for(draw,text,typeface,width)
        if len(lines)*(size+10)<=height:return typeface,lines,size+10
    return typeface,lines[:4],32

def ellipsis(draw,text,typeface,width):
    while text and draw.textlength(text+'…',font=typeface)>width:text=text[:-1]
    return text.rstrip()+'…'


@lru_cache(maxsize=1)
def background():
    with Image.open(ROOT/'assets'/'cards'/'undead_crest.png') as art:
        return ImageOps.fit(art.convert('RGB'),SIZE,method=Image.Resampling.LANCZOS)

@lru_cache(maxsize=7)
def rarity_background(rarity):
    """Original per-rarity scenes: no Warcraft sprites or external artwork."""
    shades={
      'Common':('#22252d','#121319','#68707e'),
      'Uncommon':('#142c23','#0c1517','#55c88d'),
      'Rare':('#152e4b','#0b1528','#54baf7'),
      'Epic':('#33184b','#100a22','#d58aff'),
      'Legendary':('#3e2917','#160e12','#ffd379'),
      'Mythic':('#441831','#1e1124','#ff6cb5')
    }
    sky,deep,shine=shades.get(rarity,shades['Common'])
    def color(value):return tuple(int(value[i:i+2],16) for i in (1,3,5))
    c1,c2,accent=map(color,(sky,deep,shine))
    base=Image.new('RGB',SIZE);draw=ImageDraw.Draw(base)
    for y in range(SIZE[1]):
        t=y/SIZE[1]
        draw.line((0,y,SIZE[0],y), fill=tuple(int(c1[i]*(1-t)+c2[i]*t) for i in range(3)))
    scene=Image.new('RGBA',SIZE,(0,0,0,0));d=ImageDraw.Draw(scene,'RGBA')
    rng=random.Random('critbot-art-'+rarity)
    center=(940,303)
    if rarity=='Common':
        # Understated forged slate; little ornament, little fanfare.
        for x in range(780,1250,62):d.line((x,0,x-125,640),fill=accent+(23,),width=2)
        for y in range(100,600,58):d.line((765,y,1200,y),fill=accent+(28,),width=1)
        d.rounded_rectangle((815,154,1068,455),radius=15,outline=accent+(130,),width=5)
        d.polygon([(945,186),(1015,245),(1000,371),(940,418),(873,371),(866,247)],fill=accent+(65,),outline=accent+(160,))
        d.text((905,260),'I',font=font(105,'serif'),fill=accent+(145,))
    if rarity=='Uncommon':
        # Forest laurel wreath with carved emerald medallion.
        for side in (-1,1):
            for i in range(9):
                a=i*.23+.15;x=center[0]+side*(102+22*abs(i-4)/5);y=120+i*45
                d.ellipse((x-19,y-11,x+19,y+11),fill=accent+(68,),outline=accent+(150,),width=2)
                d.line((x,y,x-side*24,y+15),fill=accent+(120,),width=2)
        d.ellipse((823,173,1065,421),outline=accent+(135,),width=7)
        d.polygon([(940,191),(1011,259),(940,374),(870,259)],fill=accent+(60,),outline=accent+(200,))
        d.text((910,252),'✦',font=font(56,'serif'),fill=accent+(220,))
    if rarity=='Rare':
        # Diamond-crystal lattice, glinting star and geometric aura.
        for rad in (98,152,201):
            d.polygon([(940,304-rad),(940+rad,304),(940,304+rad),(940-rad,304)],outline=accent+(80,),width=4)
        for i in range(10):
            x=730+i*46;y=rng.randrange(85,495)
            d.polygon([(x,y-23),(x+13,y),(x,y+23),(x-13,y)],fill=accent+(60,),outline=accent+(120,))
        d.polygon([(940,178),(1020,265),(983,382),(897,382),(860,265)],fill=accent+(80,),outline=accent+(235,))
        d.line((940,178,940,381),fill=(234,253,255,145),width=5)
    if rarity in ('Epic','Legendary','Mythic'):
        # High tiers earn a much larger radial treatment, rays, rings, and particles.
        rays={'Epic':18,'Legendary':28,'Mythic':23}[rarity]
        for i in range(rays):
            theta=2*3.14159*i/rays
            x,y=center
            inner=95;outer=320+(i%3)*27
            a=(x+math.cos(theta-.065)*inner,y+math.sin(theta-.065)*inner)
            b=(x+math.cos(theta)*outer,y+math.sin(theta)*outer)
            c=(x+math.cos(theta+.065)*inner,y+math.sin(theta+.065)*inner)
            d.polygon([a,b,c],fill=accent+(23 if rarity=='Epic' else 47,))
        for rad,width,alpha in ((103,7,215),(154,3,150),(193,2,90)):
            d.ellipse((940-rad,304-rad,940+rad,304+rad),outline=accent+(alpha,),width=width)
        for i in range(7):
            theta=2*3.14159*i/7; x=940+math.cos(theta)*155;y=304+math.sin(theta)*155
            d.polygon([(x,y-11),(x+7,y),(x,y+11),(x-7,y)],fill=accent+(225,))
        if rarity=='Epic':
            d.polygon([(940,180),(1007,247),(994,347),(940,425),(880,347),(870,247)],fill=accent+(65,),outline=accent+(235,))
            d.text((908,253),'✦',font=font(74,'serif'),fill=(247,215,255,255))
        elif rarity=='Legendary':
            crown=[(860,342),(855,235),(895,268),(940,198),(986,268),(1027,235),(1021,342)]
            d.polygon(crown,fill=accent+(115,),outline=(255,230,148,245))
            for x,y in ((855,235),(940,198),(1027,235)):
                d.ellipse((x-9,y-9,x+9,y+9),fill=(255,244,204,255))
            d.line((861,356,1018,356),fill=(255,218,127,245),width=8)
        else:
            for i in range(6):
                x=940+math.cos(i*1.05)*95;y=304+math.sin(i*1.05)*95
                d.ellipse((x-8,y-8,x+8,y+8),fill=accent+(180,))
            d.text((902,267),'✧',font=font(80,'serif'),fill=(255,222,249,255))
    if rarity != 'Common':
        for i in range({'Uncommon':18,'Rare':29,'Epic':48,'Legendary':85,'Mythic':70}.get(rarity,10)):
            x=rng.randrange(755,1190);y=rng.randrange(40,580);r=rng.choice([1,2,2,3,4]);
            d.ellipse((x-r,y-r,x+r,y+r),fill=accent+(rng.randrange(70,230),))
    return Image.alpha_composite(base.convert('RGBA'),scene)


TIER_HEADLINES={
 'Common':'A NEW MILESTONE','Uncommon':'AN UNCOMMON FIND','Rare':'RARE DISCOVERY',
 'Epic':'✦ EPIC TRIUMPH ✦','Legendary':'A LEGEND IS FORGED','Mythic':'MYTHIC GLORY'
}

def render_unlock_card(achievement,member_name,avatar_bytes=None,issued_at=None):
    rarity=clean(achievement['rarity'],20).title()
    if rarity not in STYLES:rarity='Common'
    accent,dim,border,particles=STYLES[rarity]
    brand=achievement.get('_brand') if isinstance(achievement,dict) else None
    brand=brand or {}
    accent=brand.get('accent') or accent
    card=Image.new('RGBA',SIZE,'#10121b') if brand.get('theme')=='minimal' else rarity_background(rarity).copy()
    overlay=Image.new('RGBA',SIZE,(0,0,0,dim));card=Image.alpha_composite(card,overlay)
    # Native UI layers keep the typography clear without altering the art asset.
    shade=Image.new('RGBA',SIZE);sh=ImageDraw.Draw(shade)
    for x in range(SIZE[0]):
        alpha=int(125*max(0,1-x/930))
        sh.line((x,0,x,SIZE[1]),fill=(8,7,13,alpha))
    sh.rectangle((0,475,1200,640),fill=(8,7,13,140))
    card=Image.alpha_composite(card,shade)
    # Bundled badge icon appears in the Discord achievement card itself.
    try:
        from .achievement_catalog import valid_icon_path
        rel=valid_icon_path(achievement.get('icon') if isinstance(achievement,dict) else achievement['icon'])
        if rel:
            with Image.open(ROOT/'static'/rel) as art:
                badge_art=ImageOps.contain(art.convert('RGBA'),(172,172),Image.Resampling.LANCZOS)
                frame=Image.new('RGBA',(196,196),(9,7,13,0))
                fd=ImageDraw.Draw(frame)
                fd.rounded_rectangle((1,1,194,194),radius=24,fill=(13,10,16,160))
                frame.alpha_composite(badge_art,((196-badge_art.width)//2,(196-badge_art.height)//2))
                card.alpha_composite(frame,(845,195))
    except (OSError,ValueError):
        pass
    glow=Image.new('RGBA',SIZE);gd=ImageDraw.Draw(glow)
    color=tuple(int(accent[i:i+2],16) for i in (1,3,5))
    if rarity in ('Epic','Legendary','Mythic'):
        gd.rounded_rectangle((16,16,1183,623),radius=22,outline=color+(180,),width=4)
        card=Image.alpha_composite(card,glow.filter(ImageFilter.GaussianBlur(12)))
    draw=ImageDraw.Draw(card)
    outline=[(36,16),(1164,16),(1184,36),(1184,604),(1164,624),(36,624),(16,604),(16,36)]
    draw.line(outline+[outline[0]],fill=accent,width=border)
    draw.line((48,30,460,30),fill=accent,width=border)
    draw.line((48,609,370,609),fill=accent,width=border)
    seed=hashlib.sha256((str(achievement['name'])+str(member_name)).encode()).hexdigest()
    rng=random.Random(seed)
    for _ in range(particles):
        x,y=rng.randint(810,1160),rng.randint(90,463);r=rng.choice([1,1,2,3])
        draw.ellipse((x-r,y-r,x+r,y+r),fill=color+(rng.randint(130,235),))
        if r==3:
            draw.line((x-6,y,x+6,y),fill=color+(120,),width=1)
            draw.line((x,y-6,x,y+6),fill=color+(120,),width=1)
    draw.text((64,48),clean(brand.get('name','FLICK THE CRIT'),30),font=font(22,'bold'),fill='#efcf94')
    draw.text((1063,51),'CRITBOT',font=font(14,'bold'),fill='#d4c5d5')
    pill_text=rarity.upper()+' ACHIEVEMENT'
    pill_width=int(draw.textlength(pill_text,font=font(15,'bold')))+32
    draw.rounded_rectangle((64,95,64+pill_width,132),radius=7,fill='#221b2d',outline=accent,width=1)
    draw.text((80,104),pill_text,font=font(15,'bold'),fill=accent)
    draw.text((64,156),TIER_HEADLINES.get(rarity,'ACHIEVEMENT UNLOCKED'),font=font(15,'bold'),fill=accent)
    title=clean(achievement['name'],80) or 'Guild Achievement'
    face,lines,spacing=title_layout(draw,title)
    y=188
    for line in lines:
        draw.text((65,y+2),line,font=face,fill='#000000')
        draw.text((64,y),line,font=face,fill='#fff0d5');y+=spacing
    body=clean(achievement['description'],500)
    body_font=font(21)
    body_lines=lines_for(draw,body,body_font,650)
    if len(body_lines)>3:body_lines=body_lines[:2]+[ellipsis(draw,body_lines[2],body_font,650)]
    for i,line in enumerate(body_lines):draw.text((64,359+i*29),line,font=body_font,fill='#c5bdce')
    draw.line((64,466,750,466),fill='#5b475e',width=1)
    avatar=None
    if avatar_bytes and len(avatar_bytes)<=2*1024*1024:
        try:
            with Image.open(io.BytesIO(avatar_bytes)) as image:
                if image.width<=2048 and image.height<=2048:
                    avatar=ImageOps.fit(image.convert('RGBA'),(72,72),method=Image.Resampling.LANCZOS)
        except Exception:pass
    draw.ellipse((62,498,138,574),fill='#2e243a',outline=accent,width=2)
    if avatar:
        mask=Image.new('L',(72,72));ImageDraw.Draw(mask).ellipse((0,0,71,71),fill=255)
        card.paste(avatar,(64,500),mask)
    else:
        letter=(clean(member_name,80) or 'F')[0].upper()
        draw.text((88,514),letter,font=font(29,'bold'),fill=accent)
    draw=ImageDraw.Draw(card)
    draw.text((158,500),'EARNED BY',font=font(12,'bold'),fill='#a89cb5')
    name=clean(member_name,80) or 'Guild Member'
    for size in range(26,11,-1):
        member_font=font(size,'bold')
        if draw.textlength(name,font=member_font)<=360:break
    if draw.textlength(name,font=member_font)>360:name=ellipsis(draw,name,member_font,360)
    draw.text((157,524),name,font=member_font,fill='#f6edf7')
    draw.rounded_rectangle((563,501,746,572),radius=9,fill=(30,23,36,235),outline=accent,width=1)
    points=max(0,int(achievement['points']))
    draw.text((581,505),f'+{points:,}',font=font(30,'bold'),fill=accent)
    draw.text((583,547),'ACHIEVEMENT POINTS',font=font(10,'bold'),fill='#c9bdcf')
    date=issued_at or datetime.now(ZoneInfo('America/New_York'))
    draw.text((64,589),date.strftime('%b %d, %Y').upper()+'  •  '+clean(brand.get('name','FLICK THE CRIT'),30),font=font(12),fill='#a999ad')
    draw.text((900,589),clean(brand.get('tagline','THE CRIT IS A MYTH'),30),font=font(10,'bold'),fill='#bfa3c8')
    output=io.BytesIO();card.convert('RGB').save(output,format='PNG',compress_level=6)
    return output.getvalue()
