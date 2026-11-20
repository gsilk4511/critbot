import asyncio,logging,os
import discord
from .store import commercial,guild_id,save_entitlements,plan

def install(bot,connect):
    async def refresh():
        sku=os.getenv('CRITBOT_PREMIUM_SKU_ID','').strip();gid=guild_id()
        if not commercial() or not sku.isdecimal() or not gid.isdecimal():return
        entries=[e async for e in bot.entitlements(limit=None,skus=[discord.Object(id=int(sku))],guild=discord.Object(id=int(gid)),exclude_ended=True,exclude_deleted=True)]
        with connect() as db:save_entitlements(db,entries,sku)
    async def worker():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:await refresh()
            except Exception:logging.exception('Premium subscription sync failed; cached access expires after five minutes')
            await asyncio.sleep(60)
    @bot.tree.command(name='premium',description='See Critbot Free and Premium for this server')
    async def premium(interaction:discord.Interaction):
        with connect() as db:current=plan(db)
        embed=discord.Embed(title='Critbot Premium',description='Free: 3 automatic rules, manual achievements, member collections, rankings, events and suggestions.\n\nPremium: unlimited automatic rules, branded unlock cards, seasonal competitions, stats exports and bulk staff actions.',color=0xE3BC77)
        embed.add_field(name='This server',value=current['source'],inline=False)
        sku=os.getenv('CRITBOT_PREMIUM_SKU_ID','').strip();view=None
        if sku.isdecimal() and commercial() and not current['premium']:
            view=discord.ui.View();view.add_item(discord.ui.Button(style=discord.ButtonStyle.premium,sku_id=int(sku)))
        elif commercial() and not current['premium']:embed.set_footer(text='Paid subscriptions are not available yet.')
        await interaction.response.send_message(embed=embed,view=view,ephemeral=True)
    @bot.tree.command(name='season',description='Show this server’s current seasonal competition')
    async def season(interaction:discord.Interaction):
        import time
        from .store import allowed
        with connect() as db:
            if not allowed(db,'seasons'):
                await interaction.response.send_message('Seasonal competitions are included in Premium. Use /premium.',ephemeral=True);return
            row=db.execute('SELECT * FROM guild_seasons ORDER BY CASE WHEN closed=0 AND ends>? THEN 0 ELSE 1 END,id DESC LIMIT 1',(time.time(),)).fetchone()
            if not row:
                await interaction.response.send_message('No competition has been created yet.',ephemeral=True);return
            leaders=db.execute("SELECT s.score,COALESCE(m.display_name,s.member_id) AS name FROM season_scores s LEFT JOIN member_directory m ON m.member_id=s.member_id WHERE season_id=? AND score>0 ORDER BY score DESC,s.member_id LIMIT 10",(row['id'],)).fetchall()
        lines=[f"**{i}.** {discord.utils.escape_markdown(p['name'])} — **{int(p['score']):,}**" for i,p in enumerate(leaders,1)]
        embed=discord.Embed(title=row['title'],description='\n'.join(lines) or 'No counted activity yet.',color=0xE3BC77)
        embed.set_footer(text=('Counted messages' if row['metric']=='messages' else 'Voice seconds')+' • '+('Ended' if row['closed'] or row['ends']<=time.time() else 'Active'))
        await interaction.response.send_message(embed=embed)
    return worker,refresh
