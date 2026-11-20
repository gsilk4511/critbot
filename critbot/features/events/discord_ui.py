import asyncio,logging
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from .store import describe,participants,rsvp,make_dungeon_post,CLASS_ROLES
from .group_views import add_controls
from .presentation import event_card

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



def native_event_details(row):
    start=datetime.fromisoformat(row['starts_at']).astimezone(timezone.utc)
    end=start+timedelta(hours=3 if row['kind']=='raid' else 2)
    description=(row['description'].strip() or 'Official Flick the Crit guild event')[:800]
    # Unique marker allows the bot to recover safely after a network timeout.
    description+=f'\n\nCritBot Event #{row["id"]}'
    return dict(name=row['title'][:100],start_time=start,end_time=end,
                location=(row['location'].strip() or 'In-game / Discord')[:100],description=description)

async def reconcile_native_events(guild,connect):
    """Create/update Discord Scheduled Events for timed guild events ONLY.

    Dungeon quick-fill posts are deliberately excluded. A backoff avoids retry spam
    when Manage Events permission is missing or Discord is unavailable.
    """
    now=datetime.now(timezone.utc)
    with connect() as db:
        candidates=db.execute("""SELECT * FROM guild_events
            WHERE kind!='dungeon' AND message_id!='' AND guild_id=?
            AND status NOT IN ('deleting','delete_failed')
            AND (scheduled_event_id='' OR scheduled_synced_revision<revision)
            AND (scheduled_retry_at='' OR scheduled_retry_at<=?)
            ORDER BY id LIMIT 3""",(str(guild.id),now.isoformat())).fetchall()
    for row in candidates:
        try:
            if row['status'] not in ('cancelled','completed') and datetime.fromisoformat(row['starts_at'])<=now and not row['scheduled_event_id']:
                raise ValueError('Cannot create a Discord Scheduled Event for a past start time.')
            event_id=str(row['scheduled_event_id'] or '')
            scheduled=None
            if event_id:
                try:scheduled=await guild.fetch_scheduled_event(int(event_id),with_counts=False)
                except discord.NotFound:
                    raise ValueError('Linked Discord Scheduled Event was deleted; restore or clear the link manually.')
            if not scheduled and row['status'] not in ('cancelled','completed'):
                # Recover a previous successful create when the API response timed out.
                marker=f'CritBot Event #{row["id"]}'
                existing=await guild.fetch_scheduled_events(with_counts=False)
                scheduled=next((e for e in existing if marker in (e.description or '')),None)
                if scheduled is None:
                    scheduled=await guild.create_scheduled_event(**native_event_details(row),
                        reason=f'CritBot scheduled guild event #{row["id"]}')
                event_id=str(scheduled.id)
                with connect() as db:
                    db.execute('UPDATE guild_events SET scheduled_event_id=? WHERE id=?',(event_id,row['id']))
            if scheduled and row['status']=='cancelled':
                if scheduled.status==discord.EventStatus.scheduled:await scheduled.cancel()
            elif scheduled and row['status']=='posted' and row['scheduled_event_id']:
                if scheduled.status==discord.EventStatus.scheduled:
                    await scheduled.edit(**native_event_details(row),reason='CritBot guild event updated')
            with connect() as db:
                db.execute("""UPDATE guild_events SET scheduled_synced_revision=?,scheduled_retry_at='',scheduled_error=''
                    WHERE id=?""",(row['revision'],row['id']))
        except Exception as exc:
            logging.exception('Discord Scheduled Event sync failed (CritBot id %s)',row['id'])
            retry=(now+timedelta(minutes=5)).isoformat()
            with connect() as db:
                db.execute('UPDATE guild_events SET scheduled_retry_at=?,scheduled_error=? WHERE id=?',
                    (retry,str(exc)[:400],row['id']))

def install(bot,connect,guild_id):
    # Any guild member can create a quick-fill dungeon post from the Discord channel.
    # This command is exempt from the achievement/admin channel-only restriction.
    @bot.tree.command(name='dungeon',description='Find a dungeon group: post open tank, healer and DPS slots')
    @app_commands.describe(dungeon='Dungeon name (e.g. RFC)', character='Your in-game character name',
        cls='Your character class',role='Your role',notes='Optional details or level range')
    @app_commands.choices(cls=[app_commands.Choice(name=c,value=c) for c in CLASS_ROLES],
        role=[app_commands.Choice(name=r,value=r) for r in ('Tank','Healer','DPS')])
    async def dungeon(interaction:discord.Interaction,dungeon:str,character:str,
                      cls:app_commands.Choice[str],role:app_commands.Choice[str],notes:str=''):
        if interaction.guild is None or interaction.user.bot or (guild_id.isdecimal() and str(interaction.guild_id)!=guild_id):
            await interaction.response.send_message('This is for members of the configured guild.',ephemeral=True);return
        try:
            await safe_channel(bot,interaction.guild,str(interaction.channel_id))
            with connect() as db:
                # Only one active listing per organizer: close the old group first.
                existing=db.execute("""SELECT id FROM guild_events WHERE kind='dungeon'
                    AND json_extract(config_json,'$.leader_id')=?
                    AND status IN ('queued','posting','posted','full','started') LIMIT 1""",
                    (str(interaction.user.id),)).fetchone()
                if existing:raise ValueError('You already have an open dungeon group. Close it before posting another.')
                new_id=make_dungeon_post(db,title=dungeon,leader_id=interaction.user.id,
                    leader_toon=character,cls=cls.value,role=role.value,
                    channel_id=interaction.channel_id,description=notes)
            await interaction.response.send_message(
                f'✅ Your **{discord.utils.escape_markdown(dungeon[:80])}** LFG post is queued here. '
                'Members can join by role/class and enter their character name. '
                '**No Discord Scheduled Event will be created.**',ephemeral=True)
        except ValueError as err:
            await interaction.response.send_message(str(err),ephemeral=True)
        except Exception:
            logging.exception('Discord dungeon creation failed')
            await interaction.response.send_message('Could not create this dungeon group. Check bot channel permissions.',ephemeral=True)

    class EventView(discord.ui.View):
        def __init__(self,event_id,closed=False):
            super().__init__(timeout=None);self.event_id=event_id
            with connect() as db:row=db.execute('SELECT * FROM guild_events WHERE id=?',(event_id,)).fetchone()
            if row and row['kind']!='general':
                add_controls(self,connect,describe(row),closed);return
            for choice,label,style in [('going','Going',discord.ButtonStyle.success),('maybe','Maybe',discord.ButtonStyle.secondary),('declined',"Can't make it",discord.ButtonStyle.secondary)]:
                button=discord.ui.Button(label=label,style=style,custom_id=f'critbot:event:{event_id}:{choice}',disabled=closed)
                async def callback(interaction,choice=choice):
                    if interaction.guild is None or interaction.user.bot:
                        await interaction.response.send_message('RSVPs are for server members.',ephemeral=True);return
                    await interaction.response.defer(ephemeral=True)
                    try:
                        with connect() as db:rsvp(db,self.event_id,interaction.user.id,interaction.user.display_name,choice,interaction.guild_id,interaction.channel_id,interaction.message.id)
                        await interaction.followup.send({'going':'You’re on the Going list.','maybe':'You’re on the Maybe list.','declined':'Your RSVP is set to Can’t make it.'}[choice],ephemeral=True)
                    except ValueError as error:await interaction.followup.send(str(error),ephemeral=True)
                    except Exception:
                        logging.exception('Event RSVP failed');await interaction.followup.send('Could not save your RSVP. Try again.',ephemeral=True)
                button.callback=callback;self.add_item(button)
    def embed(event):
        with connect() as db:people=participants(db,event['id'])
        return event_card(event,people)
    async def step():
        guild=bot.get_guild(int(guild_id)) if guild_id.isdecimal() else (bot.guilds[0] if len(bot.guilds)==1 else None)
        if guild is None:return
        with connect() as db:
            db.execute("UPDATE guild_events SET status='expired',revision=revision+1 WHERE kind='dungeon' AND status IN ('posted','full') AND datetime(created_at)<=datetime('now','-24 hours')")
        with connect() as db:
            queued=db.execute("SELECT * FROM guild_events WHERE status='queued' ORDER BY id LIMIT 3").fetchall()
        for event in queued:
            with connect() as db:
                claimed=db.execute("UPDATE guild_events SET status='posting' WHERE id=? AND status='queued'",(event['id'],)).rowcount
            if not claimed:continue
            attempted=False
            try:
                channel=await safe_channel(bot, guild, event['channel_id'])
                if getattr(channel,'guild',None) is None or channel.guild.id!=guild.id:raise ValueError('Selected channel is not in this server.')
                permissions=channel.permissions_for(guild.me)
                if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):raise ValueError('Critbot needs View Channel, Send Messages and Embed Links in the event channel.')
                attempted=True
                message=await channel.send(embed=embed(event),view=EventView(event['id']),allowed_mentions=discord.AllowedMentions.none())
                with connect() as db:db.execute("UPDATE guild_events SET status='posted',guild_id=?,message_id=?,synced_revision=?,last_error='' WHERE id=?",(str(guild.id),str(message.id),event['revision'],event['id']))
                bot.add_view(EventView(event['id']),message_id=message.id)
            except Exception as error:
                definite=not attempted or isinstance(error,(discord.Forbidden,discord.NotFound))
                status='failed' if definite else 'uncertain'
                with connect() as db:db.execute('UPDATE guild_events SET status=?,last_error=? WHERE id=?',(status,str(error)[:400],event['id']))
                logging.exception('Event publication failed')
        with connect() as db:
            deleting=db.execute("SELECT * FROM guild_events WHERE status='deleting' ORDER BY id LIMIT 5").fetchall()
        for event in deleting:
            try:
                if event['guild_id']!=str(guild.id):raise ValueError('Posted event belongs to a different server.')
                try:
                    channel=await safe_channel(bot, guild, event['channel_id'])
                    message=await channel.fetch_message(int(event['message_id']))
                    await message.delete()
                except discord.NotFound:pass
                if event['scheduled_event_id']:
                    try:
                        scheduled=await guild.fetch_scheduled_event(int(event['scheduled_event_id']),with_counts=False)
                        await scheduled.delete(reason='CritBot event deleted')
                    except discord.NotFound:pass
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('DELETE FROM guild_event_members WHERE event_id=?',(event['id'],))
                    db.execute("DELETE FROM guild_events WHERE id=? AND status='deleting'",(event['id'],))
            except Exception as error:
                with connect() as db:db.execute("UPDATE guild_events SET status='delete_failed',last_error=? WHERE id=?",(str(error)[:400],event['id']))
                logging.exception('Event deletion failed')
        with connect() as db:
            dirty=db.execute("SELECT * FROM guild_events WHERE message_id!='' AND status NOT IN ('deleting','delete_failed') AND revision>synced_revision ORDER BY id LIMIT 5").fetchall()
        for event in dirty:
            try:
                if event['guild_id']!=str(guild.id):raise ValueError('Posted event belongs to a different server.')
                channel=await safe_channel(bot, guild, event['channel_id'])
                message=await channel.fetch_message(int(event['message_id']))
                await message.edit(embed=embed(event),view=EventView(event['id'],event['status']!='posted'),allowed_mentions=discord.AllowedMentions.none())
                error=''
            except Exception as exc:error=str(exc)[:400];logging.exception('Event message update failed')
            with connect() as db:db.execute('UPDATE guild_events SET synced_revision=?,last_error=? WHERE id=?',(event['revision'],error,event['id']))
        await reconcile_native_events(guild,connect)
    async def worker():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:await step()
            except Exception:logging.exception('Event worker failed')
            await asyncio.sleep(5)
    def start():
        with connect() as db:
            db.execute("UPDATE guild_events SET status='uncertain',last_error='Bot restarted during publication. Check the selected channel before retrying.' WHERE status='posting'")
            posted=db.execute("SELECT id,message_id,status FROM guild_events WHERE message_id!=''").fetchall()
        for event in posted:bot.add_view(EventView(event['id'],event['status']!='posted'),message_id=int(event['message_id']))
        return asyncio.create_task(worker())
    return start,step,EventView
