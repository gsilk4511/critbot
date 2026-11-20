import asyncio,logging
import discord
from .store import submit,vote,totals

async def safe_channel(bot, guild, channel_id):
    """Only publish to a channel within the configured server, including manual IDs."""
    channel=guild.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
    if getattr(getattr(channel, 'guild', None), 'id', None) != guild.id:
        raise ValueError('Channel ID is not part of this Discord server.')
    if not hasattr(channel, 'send'):
        raise ValueError('Discord channel cannot receive messages.')
    me=guild.me
    if me is None:
        raise ValueError('Bot membership could not be verified.')
    perms=channel.permissions_for(me)
    if not (perms.view_channel and perms.send_messages and perms.embed_links):
        raise ValueError('CritBot needs View Channel, Send Messages, and Embed Links permissions.')
    return channel


def install(bot,connect,guild_id):
    class SuggestionModal(discord.ui.Modal,title='Suggest something for Flick the Crit'):
        headline=discord.ui.TextInput(label='Idea title',max_length=80)
        details=discord.ui.TextInput(label='What would you like and why?',style=discord.TextStyle.paragraph,max_length=1500)
        def __init__(self,source):super().__init__();self.source=source
        async def on_submit(self,interaction):
            if interaction.guild is None or interaction.user.bot:
                await interaction.response.send_message('Suggestions are for server members.',ephemeral=True);return
            await interaction.response.defer(ephemeral=True)
            try:
                with connect() as db:sid=submit(db,str(self.headline),str(self.details),interaction.user.id,interaction.user.display_name,interaction.guild_id,interaction.channel_id,self.source)
                await interaction.followup.send(f'Idea #{sid} saved. Critbot will post it shortly.',ephemeral=True)
            except ValueError as error:await interaction.followup.send(str(error),ephemeral=True)
            except Exception:
                logging.exception('Suggestion submission failed');await interaction.followup.send('Could not save this idea. Try again.',ephemeral=True)
    class BoardView(discord.ui.View):
        def __init__(self,disabled=False):
            super().__init__(timeout=None)
            button=discord.ui.Button(label='Board moved' if disabled else 'Submit idea',style=discord.ButtonStyle.primary,custom_id='critbot:suggestions:submit',disabled=disabled)
            async def callback(interaction):
                if interaction.guild is None or interaction.user.bot:
                    await interaction.response.send_message('Suggestions are for server members.',ephemeral=True);return
                with connect() as db:board=db.execute('SELECT * FROM suggestion_board WHERE id=1').fetchone()
                if board['state']!='posted' or (board['guild_id'],board['channel_id'],board['message_id'])!=(str(interaction.guild_id),str(interaction.channel_id),str(interaction.message.id)):
                    await interaction.response.send_message('This suggestion board is no longer active.',ephemeral=True);return
                await interaction.response.send_modal(SuggestionModal(interaction.message.id))
            button.callback=callback;self.add_item(button)
    class VoteView(discord.ui.View):
        def __init__(self,sid,closed=False):
            super().__init__(timeout=None)
            for direction,label,style in [(1,'Support',discord.ButtonStyle.success),(-1,'Oppose',discord.ButtonStyle.secondary)]:
                button=discord.ui.Button(label=label,style=style,custom_id=f'critbot:suggestion:{sid}:{direction}',disabled=closed)
                async def callback(interaction,direction=direction):
                    if interaction.guild is None or interaction.user.bot:
                        await interaction.response.send_message('Voting is for server members.',ephemeral=True);return
                    await interaction.response.defer(ephemeral=True)
                    try:
                        with connect() as db:result=vote(db,sid,interaction.user.id,direction,interaction.guild_id,interaction.channel_id,interaction.message.id)
                        await interaction.followup.send(result,ephemeral=True)
                    except ValueError as error:await interaction.followup.send(str(error),ephemeral=True)
                    except Exception:
                        logging.exception('Suggestion vote failed');await interaction.followup.send('Could not save your vote. Try again.',ephemeral=True)
                button.callback=callback;self.add_item(button)
    def card(row):
        with connect() as db:count=totals(db,row['id'])
        colors={'open':0xE3BC77,'planned':0x779CE3,'completed':0x69B891,'declined':0x9898A4}
        embed=discord.Embed(title=f"💡 {row['title']}",description=row['body'],color=colors[row['status']])
        embed.set_author(name=f"FLICK THE CRIT • IDEA #{row['id']}")
        embed.add_field(name='Community vote',value=f"**{count['support']}** support · **{count['oppose']}** oppose · Score **{count['score']:+d}**",inline=False)
        if row['staff_note']:embed.add_field(name='Staff response',value=row['staff_note'],inline=False)
        embed.set_footer(text=f"{'Archived' if row['archived'] else row['status'].title()} • By {row['author_name']}"+(' • Click your vote again to remove it' if row['status']=='open' and not row['archived'] else ' • Voting closed'))
        return embed
    def board_card(guild,board):
        destination=guild.get_channel(int(board['results_channel_id'])) if board['results_channel_id'] else None
        feed_mention=(destination.mention if destination and hasattr(destination,'mention')
                      else f"<#{board['results_channel_id']}>" if board['results_channel_id'] else 'the suggestion feed')
        embed=discord.Embed(title='💡 Suggest an Idea',
            description=f'Got an idea for Flick the Crit? Use the button below.\n\nNew suggestions will appear in {feed_mention}, where everyone can vote and staff can respond. This button stays here.',color=0xE3BC77)
        embed.set_footer(text='FLICK THE CRIT · COMMUNITY IDEAS')
        return embed
    async def step():
        guild=bot.get_guild(int(guild_id)) if guild_id.isdecimal() else (bot.guilds[0] if len(bot.guilds)==1 else None)
        if guild is None:return
        # Remove messages from Discord before purging their data.
        with connect() as db:
            deletions=db.execute("SELECT * FROM guild_suggestions WHERE delete_state='queued' ORDER BY id LIMIT 4").fetchall()
        for row in deletions:
            try:
                if row['message_id']:
                    if row['guild_id']!=str(guild.id):raise ValueError('The Discord message belongs to a different server.')
                    try:
                        channel=await safe_channel(bot, guild, row['channel_id'])
                        message=await channel.fetch_message(int(row['message_id']))
                        await message.delete()
                    except discord.NotFound:
                        pass  # Already removed or channel deleted.
                elif row['publish_state'] not in ('queued','failed'):
                    raise ValueError('Discord publication is uncertain; resolve the post before removing this item.')
                with connect() as db:
                    db.execute('DELETE FROM suggestion_votes WHERE suggestion_id=?',(row['id'],))
                    db.execute("DELETE FROM guild_suggestions WHERE id=? AND delete_state='queued'",(row['id'],))
            except Exception as exc:
                logging.exception('Suggestion %s Discord deletion failed; data retained',row['id'])
                with connect() as db:
                    db.execute("UPDATE guild_suggestions SET delete_state='failed',last_error=? WHERE id=?",(str(exc)[:400],row['id']))
        with connect() as db:board=db.execute('SELECT * FROM suggestion_board WHERE id=1').fetchone()
        if board['state']=='queued':
            with connect() as db:claimed=db.execute("UPDATE suggestion_board SET state='posting' WHERE id=1 AND state='queued'").rowcount
            if claimed:
                attempted=False
                try:
                    channel=await safe_channel(bot, guild, board['channel_id'])
                    if channel.guild.id!=guild.id:raise ValueError('Choose a channel in this server.')
                    permissions=channel.permissions_for(guild.me)
                    if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):raise ValueError('Critbot needs View Channel, Send Messages and Embed Links here.')
                    embed=board_card(guild,board)
                    attempted=True;message=await channel.send(embed=embed,view=BoardView(),allowed_mentions=discord.AllowedMentions.none())
                    with connect() as db:db.execute("UPDATE suggestion_board SET state='posted',guild_id=?,message_id=?,last_error='' WHERE id=1",(str(guild.id),str(message.id)))
                    bot.add_view(BoardView(),message_id=message.id)
                except Exception as error:
                    state='failed' if not attempted or isinstance(error,(discord.Forbidden,discord.NotFound)) else 'uncertain'
                    with connect() as db:db.execute('UPDATE suggestion_board SET state=?,last_error=? WHERE id=1',(state,str(error)[:400]))
                    logging.exception('Suggestion board publication failed')
        # Update the existing submission-button message when only the feed channel changes.
        # Reposting here would scatter duplicate buttons across Discord.
        with connect() as db:board=db.execute('SELECT * FROM suggestion_board WHERE id=1').fetchone()
        if board['state']=='posted' and board['message_id'] and board['feed_needs_sync']:
            try:
                ch=await safe_channel(bot, guild, board['channel_id'])
                msg=await ch.fetch_message(int(board['message_id']))
                await msg.edit(embed=board_card(guild,board))
                with connect() as db:
                    db.execute("UPDATE suggestion_board SET feed_needs_sync=0,last_error='' WHERE id=1 AND results_channel_id=? AND message_id=?",
                               (board['results_channel_id'],board['message_id']))
            except Exception as exc:
                with connect() as db:db.execute('UPDATE suggestion_board SET last_error=? WHERE id=1',(str(exc)[:400],))
                logging.exception('Could not update suggestion button to show the new feed')
        with connect() as db:
            retiring=db.execute("SELECT * FROM suggestion_board_retire WHERE state='queued' ORDER BY id LIMIT 3").fetchall()
        for retired in retiring:
            try:
                ch=await safe_channel(bot, guild, retired['channel_id'])
                message=await ch.fetch_message(int(retired['message_id']))
                await message.edit(view=BoardView(disabled=True))
                with connect() as db:db.execute("UPDATE suggestion_board_retire SET state='retired',last_error='' WHERE id=?",(retired['id'],))
            except Exception as exc:
                with connect() as db:db.execute("UPDATE suggestion_board_retire SET state='failed',last_error=? WHERE id=?",(str(exc)[:400],retired['id']))
                logging.warning('Could not disable old suggestion board %s: %s',retired['id'],exc)
        with connect() as db:queued=db.execute("SELECT * FROM guild_suggestions WHERE publish_state='queued' AND archived=0 AND delete_state='' ORDER BY id LIMIT 3").fetchall()
        for row in queued:
            with connect() as db:claimed=db.execute("UPDATE guild_suggestions SET publish_state='posting' WHERE id=? AND publish_state='queued' AND archived=0 AND delete_state=''",(row['id'],)).rowcount
            if not claimed:continue
            attempted=False
            try:
                if row['guild_id']!=str(guild.id):raise ValueError('Suggestion belongs to a different server.')
                channel=await safe_channel(bot, guild, row['channel_id'])
                if getattr(channel,'guild',guild).id!=guild.id:raise ValueError('The suggestion feed must be in the same Discord server.')
                perms=channel.permissions_for(guild.me) if hasattr(channel,'permissions_for') else None
                if perms is not None and not (perms.view_channel and perms.send_messages and perms.embed_links):
                    raise ValueError('CritBot needs View Channel, Send Messages and Embed Links in the suggestion feed.')
                attempted=True;message=await channel.send(embed=card(row),view=VoteView(row['id'],row['status']!='open' or bool(row['archived']) or bool(row['delete_state'])),allowed_mentions=discord.AllowedMentions.none())
                with connect() as db:db.execute("UPDATE guild_suggestions SET message_id=?,publish_state='posted',synced_revision=?,last_error='' WHERE id=?",(str(message.id),row['revision'],row['id']))
                bot.add_view(VoteView(row['id'],row['status']!='open' or bool(row['archived']) or bool(row['delete_state'])),message_id=message.id)
            except Exception as error:
                state='failed' if not attempted or isinstance(error,(discord.Forbidden,discord.NotFound)) else 'uncertain'
                with connect() as db:db.execute('UPDATE guild_suggestions SET publish_state=?,last_error=? WHERE id=?',(state,str(error)[:400],row['id']))
                logging.exception('Suggestion publication failed')
        with connect() as db:dirty=db.execute("SELECT * FROM guild_suggestions WHERE message_id!='' AND delete_state='' AND revision>synced_revision ORDER BY id LIMIT 5").fetchall()
        for row in dirty:
            try:
                if row['guild_id']!=str(guild.id):raise ValueError('Suggestion belongs to a different server.')
                channel=await safe_channel(bot, guild, row['channel_id'])
                message=await channel.fetch_message(int(row['message_id']))
                await message.edit(embed=card(row),view=VoteView(row['id'],row['status']!='open' or bool(row['archived']) or bool(row['delete_state'])),allowed_mentions=discord.AllowedMentions.none());error=''
            except Exception as exc:error=str(exc)[:400];logging.exception('Suggestion update failed')
            with connect() as db:db.execute('UPDATE guild_suggestions SET synced_revision=?,last_error=? WHERE id=?',(row['revision'],error,row['id']))
    async def worker():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:await step()
            except Exception:logging.exception('Suggestion worker failed')
            await asyncio.sleep(5)
    def start():
        with connect() as db:
            db.execute("UPDATE suggestion_board SET state='uncertain',last_error='Restarted during publication. Check Discord before retrying.' WHERE state='posting'")
            db.execute("UPDATE guild_suggestions SET publish_state='uncertain',last_error='Restarted during publication. Check Discord before retrying.' WHERE publish_state='posting'")
            board=db.execute('SELECT * FROM suggestion_board WHERE id=1').fetchone()
            posted=db.execute("SELECT id,message_id,status,archived,delete_state FROM guild_suggestions WHERE message_id!=''").fetchall()
        if board['message_id']:bot.add_view(BoardView(),message_id=int(board['message_id']))
        for row in posted:bot.add_view(VoteView(row['id'],row['status']!='open' or bool(row['archived']) or bool(row['delete_state'])),message_id=int(row['message_id']))
        return asyncio.create_task(worker())
    return start,step,BoardView,VoteView
