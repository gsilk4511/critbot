"""Discord event cards, kept separate from publication and signup handling."""
import discord
from .store import describe

THEMES={'general':('🎉','GUILD EVENT',0xE3BC77),'dungeon':('⚔️','DUNGEON PARTY',0x50C8C6),'raid':('🐉','RAID NIGHT',0xB78AFA),'custom':('✨','CUSTOM GROUP',0xF28DB4)}

def event_card(event,people):
    item=describe(event);icon,label,color=THEMES[item['kind']]
    closed=item['status'] in ('cancelled','completed','full','started','expired')
    status={'cancelled':'⛔ CANCELLED','completed':'🏁 COMPLETED','full':'👥 GROUP FULL','started':'⚔️ RUN STARTED','expired':'⌛ EXPIRED'}.get(item['status'],'🟢 SIGNUPS OPEN')
    if closed:color=0x74788D if item['status']=='completed' else 0xD76565
    card=discord.Embed(title=f"{icon} {item['title']}",color=color)
    card.set_author(name=f'FLICK THE CRIT • {label}')
    if item['kind']=='dungeon':
        leader=discord.utils.escape_markdown(item['config'].get('leader_name','Guild member'))
        active=[p for p in people if p['rsvp']=='going']
        slots=item['config']['slots']
        total=sum(max(0,int(slot['capacity'])) for slot in slots)
        remaining=max(0,total-len(active))
        state={'cancelled':'🔴 Cancelled','completed':'⚫ Completed','full':'🟡 Full','started':'🟠 In progress','expired':'⚫ Expired'}.get(item['status'],'🟢 Recruiting')
        # Short, readable summary; the three role columns carry the roster.
        card=discord.Embed(title=f"⚔️ {item['title'][:190]}",color=color)
        card.set_author(name='FLICK THE CRIT  /  GROUP FINDER')
        desc=(f"{state}   •   **{len(active)}/{total} players**   •   **{remaining} open**\n"
              f"**Leader:** {leader}")
        if item['description']:
            desc+=f"\n{discord.utils.escape_markdown(item['description'][:260])}"
        card.description=desc
        for slot in slots:
            roster=[person for person in active if person['choice']==slot['key']]
            role=slot['name']; capacity=max(0,int(slot['capacity']))
            icon={'Tank':'🛡️','Healer':'💚','DPS':'⚔️'}.get(role,'◆')
            lines=[]
            for person in roster:
                name=discord.utils.escape_markdown(str(person['name'])[:32])
                cls=discord.utils.escape_markdown(str(person.get('class_name') or '')[:18])
                lines.append(f"**{name}**"+(f"\n*{cls}*" if cls else ''))
            available=max(0,capacity-len(roster))
            if available:
                lines.append(f"*{available} open {'slot' if available==1 else 'slots'}*")
            card.add_field(name=f"{icon} {role}  {len(roster)}/{capacity}",
                           value='\n'.join(lines)[:1024] or '—',inline=True)
        card.set_footer(text=f"Group #{item['id']}  •  Use the buttons below to join or manage")
        return card
    else:
        card.description=item['description'][:1000] or 'Your next guild adventure starts here.'
        card.add_field(name='📅 When',value=f"<t:{item['timestamp']}:F> · <t:{item['timestamp']}:R>",inline=False)
        if item['location']:card.add_field(name='📍 Meetup',value=discord.utils.escape_markdown(item['location']),inline=False)
        if closed:card.description+='\n\n'+status
    if item['kind']=='general':
        for key,name in [('going','✅ Going'),('maybe','🤔 Maybe'),('declined','❌ Can’t make it')]:
            members=[p for p in people if p['rsvp']==key]
            names='\n'.join(discord.utils.escape_markdown(p['name']) for p in members[:3])[:340]
            if len(members)>3:names+=f'\n+ {len(members)-3} more'
            card.add_field(name=f'{name} · {len(members)}',value=names or '—',inline=True)
    else:
        active=[p for p in people if p['rsvp']=='going'];slots=item['config']['slots'];capacity=sum(s['capacity'] for s in slots)
        title=f"Roster · {len(active)} joined"
        if all(s['capacity'] for s in slots):title+=f" · {max(0,capacity-len(active))} open"
        for index,option in enumerate(slots):
            joined=[p for p in active if p['choice']==option['key']];cap=option['capacity']
            badge={'tank':'🛡️','healer':'💚','dps':'⚔️'}.get(option['name'].casefold(),'◆')
            names=[discord.utils.escape_markdown(p['name'])+(f" ({discord.utils.escape_markdown(p['class_name'])})" if p['class_name'] else '') for p in joined[:3]]
            detail=f"{badge} **{discord.utils.escape_markdown(option['name'])} · {len(joined)}/{cap or '∞'}**\n"
            detail+=(' · '.join(names)[:320] if names else '*Open*')
            if len(joined)>3:detail+=f' · +{len(joined)-3} more'
            card.add_field(name=title if index==0 else '\u200b',value=detail,inline=False)
    card.set_footer(text='THE CRIT IS A MYTH'+(' • Closed' if closed else ''))
    return card
