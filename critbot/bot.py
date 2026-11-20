"""Critbot achievements. Uses existing .env in parent Critbot directory."""
import os, sqlite3, asyncio, logging, sys, time, io
from pathlib import Path
import discord
from discord import app_commands
from dotenv import load_dotenv
from .automatic_achievements import init_schema, record_message, VoiceTracker
from .activity_stats import member_stats, member_progress
from .leaderboards import METRICS, ranked_members
from .channel_overrides import init_channel_sync

from .paths import ROOT, database_path
from .cards import render_unlock_card
from .features.premium.store import init_premium,allowed,commercial,branding
from .features.events.store import init_events
from .features.suggestions.store import init_suggestions
from .features.suggestions.discord_ui import install as install_suggestions
from .features.events.discord_ui import install as install_events
HERE = ROOT
TOKEN = os.getenv('DISCORD_TOKEN')
DB = database_path()
GUILD_ID = os.getenv('CRITBOT_GUILD_ID', '').strip()
# Single channel where Critbot may be used and send Discord messages.
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv('CRITBOT_ANNOUNCEMENT_CHANNEL_ID','1558705291552489504'))
ADMIN_CHANNEL_ID = int(os.getenv('CRITBOT_ADMIN_CHANNEL_ID','1555780606116495390'))
ALLOWED_CHANNEL_IDS = {ANNOUNCEMENT_CHANNEL_ID, ADMIN_CHANNEL_ID}
def effective_announcement_channel_id():
    """Owner-configured dashboard override; defaults to .env for safe rollback."""
    try:
        db=connect()
        try:
            row=db.execute('SELECT announcement_id FROM channel_route_overrides WHERE id=1').fetchone()
        finally:
            db.close()
        if row and str(row[0]).isdigit(): return int(row[0])
    except sqlite3.Error:
        pass
    return ANNOUNCEMENT_CHANNEL_ID

ALLOWED_CHANNEL_ID = ANNOUNCEMENT_CHANNEL_ID  # Backwards-compatible public channel
CHANNEL_ID = str(ANNOUNCEMENT_CHANNEL_ID)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# One instance per bot token on this computer, including copies in other folders.
# A second Python process replying with the same Discord token can cause
# "Interaction has already been acknowledged" and inconsistent channel checks.
_INSTANCE_HANDLE = None

def acquire_single_instance():
    global _INSTANCE_HANDLE
    import hashlib
    key = hashlib.sha256(TOKEN.encode('utf-8')).hexdigest()[:24]
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, True, 'Local\\Critbot_' + key)
        if not handle:
            raise RuntimeError('Cannot create Critbot instance lock')
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            raise RuntimeError('Another Critbot process is already running. Stop it first.')
        _INSTANCE_HANDLE = handle
    else:
        import fcntl
        path = HERE / ('.critbot_' + key + '.lock')
        lock_file = open(path, 'a+')
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise RuntimeError('Another Critbot process is already running.')
        _INSTANCE_HANDLE = lock_file

def connect():
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    return conn

def init_db():
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS award_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, achievement_id INTEGER NOT NULL, member_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT \'pending\', detail TEXT NOT NULL DEFAULT \'\', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        columns = {row[1] for row in db.execute('PRAGMA table_info(award_queue)')}
        if 'action' not in columns:
            db.execute("ALTER TABLE award_queue ADD COLUMN action TEXT NOT NULL DEFAULT 'award'")
        if 'silent' not in columns:
            db.execute("ALTER TABLE award_queue ADD COLUMN silent INTEGER NOT NULL DEFAULT 0")
        if 'batch_id' not in columns:
            db.execute("ALTER TABLE award_queue ADD COLUMN batch_id INTEGER")
        db.execute('''CREATE TABLE IF NOT EXISTS member_directory (
            member_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            username TEXT NOT NULL, joined_at TEXT, is_bot INTEGER NOT NULL DEFAULT 0,
            last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS bulk_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT, achievement_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, announcement_sent INTEGER NOT NULL DEFAULT 0
        )''')
        batch_columns = {row[1] for row in db.execute("PRAGMA table_info(bulk_batches)")}
        if "action" not in batch_columns:
            db.execute("ALTER TABLE bulk_batches ADD COLUMN action TEXT NOT NULL DEFAULT 'award'")

    with connect() as db:
        init_schema(db)
        # A bot-first restart must not depend on the web process having started.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='achievements'").fetchone():
            from .achievement_catalog import install_catalog
            install_catalog(db)
    with connect() as db:
        init_events(db)
        init_suggestions(db)
        init_premium(db)


intents = discord.Intents.default()
intents.members = True

class ChannelRestrictedTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if commercial() and str(interaction.guild_id)!=GUILD_ID:
            await interaction.response.send_message('This Critbot deployment is configured for another server.',ephemeral=True);return False
        # Dungeon LFG can be started in any permitted guild text channel.
        # All other commands retain the existing channel restrictions.
        if (interaction.command and interaction.command.qualified_name=='dungeon'
                and interaction.guild_id is not None
                and (not GUILD_ID.isdecimal() or str(interaction.guild_id)==GUILD_ID)):
            return True
        # Global guard, applied for every other slash-command invocation.
        if interaction.guild_id is not None and interaction.channel_id in {effective_announcement_channel_id(), ADMIN_CHANNEL_ID}:
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f'Critbot only works in <#{effective_announcement_channel_id()}> and <#{ADMIN_CHANNEL_ID}>.',
                ephemeral=True,
            )
        return False

class Client(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = ChannelRestrictedTree(self)
        self.worker = None
    async def setup_hook(self):
        if GUILD_ID.isdecimal():
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.worker = asyncio.create_task(queue_worker())
        self.member_sync = asyncio.create_task(directory_worker())
        self.channel_sync = asyncio.create_task(channel_refresh_worker())
        self.voice_worker = asyncio.create_task(voice_worker())
        self.event_worker = start_events()
        self.suggestion_worker = start_suggestions()

bot = Client()
start_events, event_step, EventView = install_events(bot, connect, GUILD_ID)
start_suggestions, suggestion_step, SuggestionBoardView, SuggestionVoteView = install_suggestions(bot, connect, GUILD_ID)
voice_tracker = VoiceTracker()
voice_lock = asyncio.Lock()

async def update_voice_tracking():
    async with voice_lock:
        guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID.isdecimal() else (bot.guilds[0] if len(bot.guilds) == 1 else None)
        if not bot.is_ready() or guild is None:
            voice_tracker.reset()
            return
        try:
            def sample():
                with connect() as db:
                    voice_tracker.sample(db, guild, time.monotonic(), time.time())
            await asyncio.to_thread(sample)
        except Exception:
            voice_tracker.reset()
            logging.exception('Automatic voice tracking failed')

@bot.event
async def on_disconnect():
    async with voice_lock:
        voice_tracker.reset()

@bot.event
async def on_resumed():
    async with voice_lock:
        voice_tracker.reset()
    await update_voice_tracking()

@bot.event
async def on_voice_state_update(member, before, after):
    guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID.isdecimal() else (bot.guilds[0] if len(bot.guilds) == 1 else None)
    if guild is not None and member.guild.id == guild.id:
        await update_voice_tracking()

async def voice_worker():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await update_voice_tracking()
        await asyncio.sleep(15)


@bot.event
async def on_message(message):
    # Observe selected guild channels without executing commands or reading content.
    if message.guild is None or message.author.bot or message.webhook_id is not None:
        return
    guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID.isdecimal() else (bot.guilds[0] if len(bot.guilds) == 1 else None)
    if guild is None or message.guild.id != guild.id:
        return
    try:
        def count_event():
            with connect() as db:
                record_message(db, message.author.id, message.channel.id, message.id)
        await asyncio.to_thread(count_event)
    except Exception:
        logging.exception('Automatic achievement message tracking failed')


async def give_award(guild, member_id, achievement_id, silent=False):
    with connect() as db:
        achievement = db.execute('SELECT * FROM achievements WHERE id=?', (achievement_id,)).fetchone()
        if achievement is None:
            return False, 'Achievement not found'
        already = db.execute('SELECT 1 FROM unlocks WHERE achievement_id=? AND member_id=?', (achievement_id, str(member_id))).fetchone()
    if already:
        return False, 'Already unlocked'
    try:
        member = guild.get_member(int(member_id)) or await guild.fetch_member(int(member_id))
    except (discord.NotFound, discord.HTTPException, ValueError):
        return False, 'Member not found in the server'
    if achievement['role_id']:
        role = guild.get_role(int(achievement['role_id']))
        if not role:
            return False, 'Configured reward role not found'
        try:
            await member.add_roles(role, reason=f"Critbot achievement: {achievement['name']}")
        except discord.Forbidden:
            return False, 'Cannot assign role. Move Critbot role above reward role.'
        except discord.HTTPException as exc:
            return False, f'Role assignment failed: {exc}'
    with connect() as db:
        cursor = db.execute('INSERT OR IGNORE INTO unlocks (achievement_id, member_id) VALUES (?, ?)', (achievement_id, str(member_id)))
    if cursor.rowcount == 0:
        return False, 'Already unlocked'
    # Always resolve the destination explicitly. A cache miss must not silently
    # swallow an announcement, and award confirmations must disclose failures.
    if silent:
        return True, 'Bulk achievement awarded and role handled'
    announcement_status = await send_unlock_announcement(guild, achievement, member)
    if announcement_status:
        return True, 'Achievement awarded, role handled, and public announcement posted.'
    return True, (f'Achievement awarded and saved, but the announcement FAILED. '
                  f'Check logs/critbot.log and run /testannouncement in the admin bot channel.')

async def resolve_announcement_channel(guild):
    # get_channel() often returns None even for a real channel: fetch instead.
    target_id=effective_announcement_channel_id()
    channel = guild.get_channel(target_id)
    if channel is None:
        channel = bot.get_channel(target_id)
    if channel is None:
        channel = await bot.fetch_channel(target_id)
    if getattr(channel, 'guild', None) is None or channel.guild.id != guild.id:
        raise ValueError(f'Channel {target_id} does not belong to guild {guild.id}')
    if not hasattr(channel, 'send'):
        raise ValueError('The permitted channel does not support message sending')
    return channel

async def send_unlock_announcement(guild, achievement, member, preview=False):
    try:
        channel = await resolve_announcement_channel(guild)
        me = guild.me or await guild.fetch_member(bot.user.id)
        permissions = channel.permissions_for(me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            logging.error('Announcement permissions missing in %s: view=%s send=%s embeds=%s',
                          effective_announcement_channel_id(), permissions.view_channel,
                          permissions.send_messages, permissions.embed_links)
            return False
        sent = False
        with connect() as db:card_access=allowed(db,'cards')
        if card_access and getattr(permissions, 'attach_files', False):
            try:
                avatar = None
                try:
                    avatar = await asyncio.wait_for(member.display_avatar.with_format('png').replace(size=256).read(), timeout=4)
                except Exception:
                    logging.info('Avatar unavailable; using member initial on unlock card')
                with connect() as db:brand=branding(db)
                styled=dict(achievement);styled['_brand']=brand
                payload = await asyncio.to_thread(render_unlock_card, styled, member.display_name, avatar)
                if len(payload) > getattr(guild, 'filesize_limit', 8*1024*1024):
                    raise ValueError('Unlock card exceeds server attachment limit')
                embed = unlock_embed(achievement, member)
                embed.set_image(url='attachment://critbot_unlock.png')
                if preview:
                    embed.title='PREVIEW • '+embed.title[:240]
                    embed.description='**Preview only — no achievement awarded.**\n'+embed.description[:3900]
                    embed.set_footer(text='PREVIEW ONLY • No achievement awarded • FLICK THE CRIT')
                await channel.send(embed=embed, file=discord.File(io.BytesIO(payload), filename='critbot_unlock.png'),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                sent = True
            except Exception:
                logging.exception('Card attachment failed; falling back to the existing unlock embed')
        if not sent:
            fallback_embed = unlock_embed(achievement, member)
            if preview:
                fallback_embed.title='PREVIEW • '+fallback_embed.title[:240]
                fallback_embed.description='**Preview only — no achievement awarded.**\n'+fallback_embed.description[:3900]
                fallback_embed.set_footer(text='PREVIEW ONLY • No achievement awarded • FLICK THE CRIT')
            await channel.send(embed=fallback_embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        logging.info('Achievement announcement posted: %s -> %s (channel %s)',
                     achievement['name'], member.id, effective_announcement_channel_id())
        return True
    except Exception:
        logging.exception('FAILED to post achievement announcement to channel %s', effective_announcement_channel_id())
        return False

# An explicit per-command check is harder to accidentally bypass than a custom
# CommandTree-only check; it also covers newly registered commands.
async def channel_only(interaction: discord.Interaction) -> bool:
    logging.info('Channel check: command=%s channel=%s', getattr(interaction.command, 'name', '?'), interaction.channel_id)
    if interaction.guild_id is not None and interaction.channel_id in {effective_announcement_channel_id(), ADMIN_CHANNEL_ID}:
        return True
    if not interaction.response.is_done():
        await interaction.response.send_message(
            f'Critbot commands only work in <#{effective_announcement_channel_id()}> and <#{ADMIN_CHANNEL_ID}>.',
            ephemeral=True,
        )
    return False

async def admin_channel_only(interaction: discord.Interaction) -> bool:
    if interaction.guild_id is not None and interaction.channel_id == ADMIN_CHANNEL_ID:
        return True
    if not interaction.response.is_done():
        await interaction.response.send_message(
            f'Use admin commands in <#{ADMIN_CHANNEL_ID}>.', ephemeral=True,
        )
    return False

async def revoke_award(guild, member_id, achievement_id):
    with connect() as db:
        achievement = db.execute('SELECT * FROM achievements WHERE id=?', (achievement_id,)).fetchone()
        if achievement is None:
            return False, 'Achievement not found'
        existing = db.execute('SELECT 1 FROM unlocks WHERE achievement_id=? AND member_id=?',
                              (achievement_id, str(member_id))).fetchone()
        if not existing:
            return False, 'Member does not have this achievement'
        shared_role = False
        if achievement['role_id']:
            shared_role = db.execute("SELECT 1 FROM unlocks u JOIN achievements a ON a.id=u.achievement_id WHERE u.member_id=? AND u.achievement_id<>? AND a.role_id=? LIMIT 1",
               (str(member_id), achievement_id, achievement['role_id'])).fetchone() is not None
    # Do not revoke a role that another unlocked achievement still grants.
    if achievement['role_id'] and not shared_role:
        try:
            member = guild.get_member(int(member_id)) or await guild.fetch_member(int(member_id))
        except (discord.NotFound, discord.HTTPException, ValueError):
            return False, 'Member not found in the server; unlock retained'
        role = guild.get_role(int(achievement['role_id']))
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason=f"Critbot achievement revoked: {achievement['name']}")
            except discord.Forbidden:
                return False, 'Cannot remove role. Move Critbot above the reward role; unlock retained'
            except discord.HTTPException as exc:
                return False, f'Role removal failed: {exc}; unlock retained'
    with connect() as db:
        db.execute('DELETE FROM unlocks WHERE achievement_id=? AND member_id=?',
                   (achievement_id, str(member_id)))
    return True, f"Revoked {achievement['name']} and removed its achievement points"



async def refresh_channel_directory(guild):
    """Refresh only channel metadata, without waiting for full member enumeration."""
    if guild is None: return
    with connect() as db:
        init_channel_sync(db)
        db.execute('DELETE FROM auto_channel_directory')
        db.executemany('INSERT INTO auto_channel_directory(channel_id,name) VALUES(?,?)',
            [(str(c.id), (c.category.name + ' / ' if c.category else '') + '#' + c.name)
             for c in guild.text_channels if guild.me and c.permissions_for(guild.me).view_channel])
        db.execute('DELETE FROM auto_voice_directory')
        db.executemany('INSERT INTO auto_voice_directory(channel_id,name) VALUES(?,?)',
            [(str(c.id), (c.category.name + ' / ' if c.category else '') + c.name)
             for c in guild.voice_channels if c != guild.afk_channel and guild.me and c.permissions_for(guild.me).view_channel])
        db.execute("UPDATE channel_sync_requests SET completed_at=CURRENT_TIMESTAMP, status='completed', detail='Discord channel list refreshed' WHERE id=1")


async def channel_refresh_worker():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID.isdecimal() else (bot.guilds[0] if len(bot.guilds)==1 else None)
            if guild:
                await refresh_channel_directory(guild)
        except Exception as error:
            logging.exception('Unable to refresh Discord channel directory')
            with connect() as db:
                init_channel_sync(db)
                db.execute("UPDATE channel_sync_requests SET status='error', detail=? WHERE id=1",(type(error).__name__,))
        await asyncio.sleep(30)


@bot.event
async def on_guild_channel_create(channel):
    guild = getattr(channel,'guild',None)
    if guild and (not GUILD_ID.isdecimal() or guild.id == int(GUILD_ID)):
        await refresh_channel_directory(guild)


@bot.event
async def on_guild_channel_delete(channel):
    guild = getattr(channel,'guild',None)
    if guild and (not GUILD_ID.isdecimal() or guild.id == int(GUILD_ID)):
        await refresh_channel_directory(guild)

async def directory_worker():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID.isdecimal() else (bot.guilds[0] if len(bot.guilds)==1 else None)
            if guild:
                with connect() as db:
                    db.execute('DELETE FROM auto_voice_directory')
                    db.executemany('INSERT INTO auto_voice_directory(channel_id,name) VALUES(?,?)',
                        [(str(c.id), (c.category.name + ' / ' if c.category else '') + c.name)
                         for c in guild.voice_channels if c != guild.afk_channel and c.permissions_for(guild.me).view_channel])
                    db.execute('DELETE FROM auto_channel_directory')
                    db.executemany('INSERT INTO auto_channel_directory(channel_id,name) VALUES(?,?)',
                        [(str(c.id), (c.category.name + ' / ' if c.category else '') + '#' + c.name)
                         for c in guild.text_channels if c.permissions_for(guild.me).view_channel])
                members = []
                async for m in guild.fetch_members(limit=None):
                    members.append((str(m.id), m.display_name, str(m),
                        m.joined_at.isoformat() if m.joined_at else None, int(m.bot)))
                with connect() as db:
                    db.executemany("""INSERT INTO member_directory(member_id, display_name, username, joined_at, is_bot)
                        VALUES (?,?,?,?,?) ON CONFLICT(member_id) DO UPDATE SET
                        display_name=excluded.display_name, username=excluded.username,
                        joined_at=excluded.joined_at, is_bot=excluded.is_bot,
                        last_seen=CURRENT_TIMESTAMP""", members)
                    if members:
                        ids = {m[0] for m in members}
                        db.executemany('DELETE FROM member_directory WHERE member_id=?',
                            [(row[0],) for row in db.execute('SELECT member_id FROM member_directory') if row[0] not in ids])
                logging.info('Member directory synced: %d members', len(members))
        except Exception:
            logging.exception('Unable to sync Discord member directory: check Server Members Intent')
        await asyncio.sleep(900)

async def queue_worker():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            with connect() as db:
                tasks = db.execute("SELECT * FROM award_queue WHERE status='pending' ORDER BY id LIMIT 10").fetchall()
            for task in tasks:
                guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID.isdecimal() else (bot.guilds[0] if len(bot.guilds)==1 else None)
                if not guild:
                    result = (False, 'Set CRITBOT_GUILD_ID in .env')
                else:
                    result = await (revoke_award(guild, task['member_id'], task['achievement_id']) if task['action'] == 'revoke' else give_award(guild, task['member_id'], task['achievement_id'], bool(task['silent'])))
                status = ('warning' if result[0] and 'announcement FAILED' in result[1] else ('completed' if result[0] else 'failed'))
                with connect() as db:
                    db.execute('UPDATE award_queue SET status=?, detail=? WHERE id=?', (status, result[1], task['id']))
            # One public recap per batch (not 200 announcements).
            with connect() as db:
                ready = db.execute("""SELECT b.id, a.name, a.rarity, b.action,
                    SUM(CASE WHEN q.status='completed' THEN 1 ELSE 0 END) AS awarded,
                    SUM(CASE WHEN q.status='failed' THEN 1 ELSE 0 END) AS failed
                    FROM bulk_batches b JOIN award_queue q ON q.batch_id=b.id
                    JOIN achievements a ON a.id=b.achievement_id
                    WHERE b.announcement_sent=0 GROUP BY b.id
                    HAVING SUM(CASE WHEN q.status='pending' THEN 1 ELSE 0 END)=0""").fetchall()
            for batch in ready:
                guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID.isdecimal() else (bot.guilds[0] if len(bot.guilds)==1 else None)
                if guild:
                    try:
                        channel = await resolve_announcement_channel(guild)
                        embed = discord.Embed(
                            title='🏆 Guild Achievement Drop' if batch['action']=='award' else '↩ Guild Achievement Revocation',
                            description=(f"**{batch['name']}**\n✦ {batch['awarded']} members earned this achievement!"
                              if batch['action']=='award' else f"**{batch['name']}**\n↩ Removed from {batch['awarded']} member collections."),
                            color=0xf0bc48 if batch['action']=='award' else 0x8a8f9b)
                        embed.set_footer(text=f"Flick the Crit • Batch #{batch['id']} • {batch['failed']} unsuccessful")
                        await channel.send(embed=embed)
                        with connect() as db:
                            db.execute('UPDATE bulk_batches SET announcement_sent=1 WHERE id=?', (batch['id'],))
                    except Exception:
                        logging.exception('Failed to send batch achievement recap')

        except Exception:
            logging.exception('Queue worker error')
        await asyncio.sleep(3)

@bot.event
async def on_ready():
    from .version import VERSION
    logging.info('CRITBOT v%s ONLINE as %s', VERSION, bot.user)

@bot.tree.command(name='critbotversion', description='Show the currently deployed CritBot release')
async def critbotversion(interaction: discord.Interaction):
    from .version import VERSION, RELEASE, CHANGES
    await interaction.response.send_message('**CritBot v'+VERSION+' — '+RELEASE+'**\n'+'\n'.join('• '+c for c in CHANGES)+'\n\nComplete history: Dashboard → Version History (bottom of sidebar).', ephemeral=True)

@bot.tree.command(name='testannouncement', description='Admin: test public announcement delivery in this channel')
@app_commands.check(admin_channel_only)
@app_commands.checks.has_permissions(manage_guild=True)
async def testannouncement(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        channel = await resolve_announcement_channel(interaction.guild)
        embed = discord.Embed(title='🏆 CRITBOT • ANNOUNCEMENT TEST',
                              description='The Hall of Glory is connected.\nFuture achievements will be announced in the public achievements channel.',
                              color=0xD9A441, timestamp=discord.utils.utcnow())
        embed.set_footer(text='FLICK THE CRIT • The Crit is a Myth')
        await channel.send(embed=embed)
        await interaction.followup.send('✅ Public announcement posted to the Critbot channel.', ephemeral=True)
    except Exception as exc:
        logging.exception('Announcement test failed')
        await interaction.followup.send(
            f'❌ Could not post. {type(exc).__name__}: {str(exc)[:400]} '
            f'— check Send Messages, Embed Links, and View Channel permissions.', ephemeral=True)

@bot.tree.command(name='testcard', description='Admin: preview an achievement card publicly without awarding it')
@app_commands.check(admin_channel_only)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(achievement='Choose a saved achievement', member='Optional: member displayed on the test card')
async def testcard(interaction: discord.Interaction, achievement: int, member: discord.Member | None = None):
    with connect() as db:access=allowed(db,'cards')
    if not access:
        await interaction.response.send_message('Unlock cards are a Premium feature. Use /premium for this server’s plan.',ephemeral=True);return
    await interaction.response.defer(ephemeral=True)
    with connect() as db:
        item = db.execute('SELECT * FROM achievements WHERE id=?', (achievement,)).fetchone()
    if item is None:
        await interaction.followup.send('Achievement not found.', ephemeral=True)
        return
    target = member or interaction.user
    ok = await send_unlock_announcement(interaction.guild, item, target, preview=True)
    await interaction.followup.send('Preview posted in the public achievement channel. No award, points or roles were changed.' if ok
                                   else 'Preview could not be posted. See logs/critbot.log.', ephemeral=True)

@testcard.autocomplete('achievement')
async def card_achievement_autocomplete(interaction: discord.Interaction, current: str):
    with connect() as db:
        rows = db.execute('SELECT id,name FROM achievements ORDER BY name COLLATE NOCASE').fetchall()
    return [app_commands.Choice(name=row['name'][:100],value=row['id']) for row in rows if current.casefold() in row['name'].casefold()][:25]

@bot.tree.command(name='ping', description='Check Critbot status')
@app_commands.check(channel_only)
async def ping(interaction: discord.Interaction):
    if not await channel_only(interaction):
        return
    await interaction.response.send_message('🏆 Critbot reporting for duty! The Crit is a myth.', ephemeral=True)

# Discord embeds have a 6000-character limit. Keep cards small and paginated.
RARITY_COLORS = {
    'common': 0x87909B, 'uncommon': 0x1EFF00, 'rare': 0x008FFF,
    'epic': 0xA335EE, 'legendary': 0xFFB62E, 'mythic': 0xE84C75,
}
RARITY_MARKS = {
    'common': '⚪', 'uncommon': '🟢', 'rare': '🔵',
    'epic': '🟣', 'legendary': '🟠', 'mythic': '🔴',
}

def rarity_color(rarity):
    return RARITY_COLORS.get(str(rarity).lower(), 0xD3A651)

def badge(achievement):
    from .achievement_catalog import icon_for_discord
    return icon_for_discord(achievement['icon'])

def bar(current, total, width=12):
    filled = round(width * current / total) if total else 0
    return '▰' * filled + '▱' * (width - filled)

def unlock_embed(achievement, member):
    rarity = str(achievement['rarity']).lower()
    name = str(achievement['name'])
    description = str(achievement['description'] or '')
    points = int(achievement['points'])
    icon = badge(achievement)
    if rarity in ('legendary', 'mythic'):
        title = f"👑  {icon}  {name}  {icon}  👑"
        headline = ('⚡ **MYTHIC FEAT OF GLORY** ⚡' if rarity == 'mythic'
                    else '🌟 **LEGENDARY ACHIEVEMENT UNLOCKED!** 🌟')
        body = (f"# {headline}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"### {member.mention} HAS ENTERED THE HALL OF LEGENDS\n"
                f"*{description}*\n\n"
                f"🏆 **{rarity.upper()}**  •  ✦ **{points:,} ACHIEVEMENT POINTS**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "**THE CRIT IS A MYTH. THE GLORY IS REAL.**")
    elif rarity == 'epic':
        title = f"💜 {icon} {name} — EPIC UNLOCK"
        body = (f"✨ **AN EPIC FEAT!**\n\n"
                f"{member.mention} just earned an **EPIC** achievement!\n"
                f"*{description}*\n\n"
                f"🟣 **EPIC**  •  ✦ **{points:,} points**")
    elif rarity == 'rare':
        title = f"🔷 {icon} {name}"
        body = (f"**RARE ACHIEVEMENT UNLOCKED**\n{member.mention}\n\n"
                f"{description}\n\n🔵 **RARE**  •  ✦ **{points:,} points**")
    elif rarity == 'uncommon':
        title = f"🟢 {icon} {name}"
        body = (f"🎉 {member.mention} unlocked an achievement!\n"
                f"{description}\n\n🟢 **UNCOMMON**  •  ✦ **{points:,} points**")
    else:
        title = f"{icon} {name}"
        body = (f"✅ {member.mention} earned an achievement.\n"
                f"{description}\n\n✦ **{points:,} points**")
    embed = discord.Embed(
        title=title[:256], description=body[:4096], color=rarity_color(rarity),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(name='FLICK THE CRIT • HALL OF GLORY', icon_url=member.display_avatar.url)
    if rarity in ('legendary', 'mythic', 'epic'):
        embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text='CRITBOT v1.01  •  The Crit is a Myth')
    return embed

class AchievementPager(discord.ui.View):
    def __init__(self, owner_id, target, rows, total, library=False):
        super().__init__(timeout=180)
        self.owner_id, self.target, self.rows, self.total = owner_id, target, rows, total
        self.library = library
        self.index = 0
        self.page_size = 5
        self.refresh_buttons()

    def refresh_buttons(self):
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index >= pages - 1

    def render(self):
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        if self.library:
            heading = 'THE ACHIEVEMENT VAULT'
            title = '📜 Flick the Crit  •  Achievements'
            description = f'**{len(self.rows)} achievements** in the guild collection'
            color = 0xC49B55
        else:
            heading = 'PERSONAL TROPHY CASE'
            title = f'🏆 {self.target.display_name}  •  Achievements'
            points = sum(int(r['points']) for r in self.rows)
            description = (f'**{points:,}** achievement points  •  **{len(self.rows)}/{self.total}** unlocked\n'
                           f'`{bar(len(self.rows), self.total)}`  '
                           f'{round(100 * len(self.rows) / self.total) if self.total else 0}% complete')
            color = 0xC49B55
        embed = discord.Embed(title=title, description=description, color=color)
        if not self.library and self.target is not None:
            embed.set_thumbnail(url=self.target.display_avatar.url)
        chunk = self.rows[self.index*self.page_size:(self.index+1)*self.page_size]
        for item in chunk:
            rarity = str(item['rarity'])
            name = f"{badge(item)}  {item['name']}"
            if self.library:
                value = f"{RARITY_MARKS.get(rarity.lower(), '✨')} **{rarity}**  •  ✦ {item['points']} pts"
                if item['description']:
                    value += f"\n*{str(item['description'])[:170]}*"
                if item['beta_exclusive']:
                    value += '\n`BETA EXCLUSIVE`'
            else:
                value = f"{RARITY_MARKS.get(rarity.lower(), '✨')} **{rarity}**  •  ✦ {item['points']} pts"
                if item['awarded_at']:
                    value += f"\nUnlocked: {str(item['awarded_at'])[:10]}"
            embed.add_field(name=name[:256], value=value[:1024], inline=False)
        if not chunk:
            embed.add_field(name='Nothing here yet', value=('New achievements will appear here.' if self.library
                            else 'Your first guild victory is waiting.'), inline=False)
        embed.set_footer(text=f'{heading}  •  Page {self.index+1}/{pages}  •  CRITBOT')
        return embed

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.channel_id not in {effective_announcement_channel_id(), ADMIN_CHANNEL_ID}:
            await interaction.response.send_message(
                f'Critbot is only available in <#{effective_announcement_channel_id()}> and <#{ADMIN_CHANNEL_ID}>.', ephemeral=True
            )
            return False
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('This menu belongs to someone else. Run the command to open your own.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary, emoji='◀️')
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self.refresh_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label='Next', style=discord.ButtonStyle.secondary, emoji='▶️')
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        self.refresh_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

class ProgressPager(AchievementPager):
    def __init__(self, owner_id, target, rows, stats):
        super().__init__(owner_id, target, rows, len(rows))
        self.stats = stats

    def render(self):
        stats = self.stats
        pages = max(1,(len(self.rows)+self.page_size-1)//self.page_size)
        embed = discord.Embed(title=f'⚡ {self.target.display_name} • Milestone Progress'[:256],
            description=(f"**{stats['messages']:,}** counted messages  •  **{stats['voice_seconds']/60:,.1f}** voice minutes\n"
                         f"**{stats['days']:,}** active days  •  **{stats['points']:,}** points  •  **{stats['unlocks']:,}** unlocks"),
            color=0x9e7cd5)
        embed.set_thumbnail(url=self.target.display_avatar.url)
        for item in self.rows[self.index*self.page_size:(self.index+1)*self.page_size]:
            current = f"{item['current']:,.1f}" if item['kind']=='voice' else f"{int(item['current']):,}"
            capped = min(item['current'],item['target'])
            embed.add_field(name=f"{badge(item)} {item['name']}"[:256],
                value=(f"`{bar(capped,item['target'])}` **{item['percent']:g}%**\n"
                       f"{current} / {item['target']:,} {item['unit']}\n{item['state']}"),inline=False)
        if not self.rows:
            embed.add_field(name='No automatic milestones configured',value='Staff can create milestones in the Critbot dashboard.',inline=False)
        embed.set_footer(text=f'FLICK THE CRIT • Page {self.index+1}/{pages} • Live totals, refresh with /progress')
        return embed

@bot.tree.command(name='progress', description='See your tracked activity and progress toward automatic achievements')
@app_commands.check(channel_only)
@app_commands.describe(member='Optional: member whose activity and milestone progress you want to see')
async def progress(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    def read_progress():
        with connect() as db:
            stats = member_stats(db, target.id)
            return stats, member_progress(db, target.id, stats)
    stats, rows = await asyncio.to_thread(read_progress)
    view = ProgressPager(interaction.user.id,target,rows,stats)
    await interaction.response.send_message(embed=view.render(),view=view,ephemeral=True)

class LeaderboardPager(AchievementPager):
    def __init__(self, owner_id, rows, metric):
        super().__init__(owner_id,None,rows,len(rows))
        self.page_size = 10
        self.metric = metric
        self.refresh_buttons()

    def render(self):
        pages=max(1,(len(self.rows)+self.page_size-1)//self.page_size)
        self.index=max(0,min(self.index,pages-1))
        self.refresh_buttons()
        mine=next((r for r in self.rows if r['member_id']==str(self.owner_id)),None)
        personal=(f"Your rank: **#{mine['rank']}** • **{mine['score_label']}**" if mine
                  else 'You are not ranked yet for this stat. Earn a positive total to enter.')
        embed=discord.Embed(title=f'🏆 Flick the Crit • {METRICS[self.metric]}',
            description=f'**{len(self.rows):,} ranked members**\n{personal}',color=0xe3bc77)
        chunk=self.rows[self.index*self.page_size:(self.index+1)*self.page_size]
        for row in chunk:
            medal={1:'🥇',2:'🥈',3:'🥉'}.get(row['rank'],'▫️')
            name=discord.utils.escape_markdown(row['display_name'])
            embed.add_field(name=f"{medal} #{row['rank']} — {name}"[:256],
                value=f"**{row['score_label']}**\n{discord.utils.escape_markdown(row['username'])}",inline=False)
        if not chunk:
            embed.add_field(name='The board is waiting',value='No synced human members have a positive total for this stat yet.',inline=False)
        embed.set_footer(text=f'Page {self.index+1}/{pages} • Ties share ranks • Cumulative totals • CRITBOT')
        return embed

@bot.tree.command(name='leaderboard', description='View Flick the Crit guild rankings')
@app_commands.check(channel_only)
@app_commands.describe(metric='Choose the stat to rank members by')
@app_commands.choices(metric=[app_commands.Choice(name=label,value=key) for key,label in METRICS.items()])
async def leaderboard(interaction: discord.Interaction, metric: str = 'points'):
    if metric not in METRICS:
        await interaction.response.send_message('Choose a valid leaderboard stat.',ephemeral=True)
        return
    def read_ranking():
        with connect() as db:
            return ranked_members(db,metric)
    rows=await asyncio.to_thread(read_ranking)
    view=LeaderboardPager(interaction.user.id,rows,metric)
    await interaction.response.send_message(embed=view.render(),view=view)

@bot.tree.command(name='achievements', description='Show your guild achievement trophy case')
@app_commands.check(channel_only)
@app_commands.describe(member='Optional: member whose achievements you want to see')
async def achievements(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    with connect() as db:
        rows = db.execute('SELECT a.name,a.icon,a.points,a.rarity,u.awarded_at FROM unlocks u '
                          'JOIN achievements a ON a.id=u.achievement_id WHERE u.member_id=? '
                          'ORDER BY u.awarded_at DESC,a.id DESC', (str(target.id),)).fetchall()
        total = db.execute('SELECT COUNT(*) FROM achievements WHERE active=1').fetchone()[0]
    view = AchievementPager(interaction.user.id, target, rows, total)
    await interaction.response.send_message(embed=view.render(), view=view)

@bot.tree.command(name='achievement_list', description='Browse the Flick the Crit achievement vault')
@app_commands.check(channel_only)
async def achievement_list(interaction: discord.Interaction):
    with connect() as db:
        rows = db.execute('SELECT name,icon,rarity,points,description,beta_exclusive '
                          'FROM achievements WHERE active=1 ORDER BY id').fetchall()
    view = AchievementPager(interaction.user.id, None, rows, len(rows), library=True)
    await interaction.response.send_message(embed=view.render(), view=view)

async def achievement_name_autocomplete(interaction: discord.Interaction, current: str):
    """Suggest achievement names; keep integer IDs behind the scenes."""
    if interaction.channel_id != ADMIN_CHANNEL_ID:
        return []
    term = current.strip().lower()
    with connect() as db:
        rows = db.execute(
            "SELECT id, name FROM achievements WHERE active=1 AND LOWER(name) LIKE ? ORDER BY name LIMIT 25",
            (f"%{term}%",),
        ).fetchall()
    return [app_commands.Choice(name=row['name'][:100], value=row['id']) for row in rows]

async def unlocked_achievement_autocomplete(interaction: discord.Interaction, current: str):
    """Only show achievements the selected member has already earned."""
    if interaction.channel_id != ADMIN_CHANNEL_ID:
        return []
    term = current.strip().lower()
    namespace = interaction.namespace
    member = getattr(namespace, 'member', None)
    if member is None or not getattr(member, 'id', None):
        return []
    with connect() as db:
        rows = db.execute(
            "SELECT a.id, a.name FROM achievements a JOIN unlocks u ON u.achievement_id=a.id "
            "WHERE u.member_id=? AND LOWER(a.name) LIKE ? ORDER BY a.name LIMIT 25",
            (str(member.id), f"%{term}%"),
        ).fetchall()
    return [app_commands.Choice(name=row['name'][:100], value=row['id']) for row in rows]

@bot.tree.command(name='awardachievement', description='Admin: award an achievement to a member')
@app_commands.check(admin_channel_only)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(achievement_id='Choose an achievement by name')
@app_commands.autocomplete(achievement_id=achievement_name_autocomplete)
async def awardachievement(interaction: discord.Interaction, member: discord.Member, achievement_id: int):
    await interaction.response.defer(ephemeral=True)
    ok, result = await give_award(interaction.guild, member.id, achievement_id)
    await interaction.followup.send(('✅ ' if ok and 'FAILED' not in result else '⚠️ ') + result, ephemeral=True)

@bot.tree.command(name='revokeachievement', description='Admin: remove an achievement from a member')
@app_commands.check(admin_channel_only)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(achievement_id='Choose an unlocked achievement by name')
@app_commands.autocomplete(achievement_id=unlocked_achievement_autocomplete)
async def revokeachievement(interaction: discord.Interaction, member: discord.Member, achievement_id: int):
    await interaction.response.defer(ephemeral=True)
    ok, result = await revoke_award(interaction.guild, member.id, achievement_id)
    await interaction.followup.send(('✅ ' if ok else '⚠️ ') + result, ephemeral=True)

@revokeachievement.error
async def revoke_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if not interaction.response.is_done():
        await interaction.response.send_message((f'Use admin commands in <#{ADMIN_CHANNEL_ID}>.' if interaction.channel_id != ADMIN_CHANNEL_ID else 'You need Manage Server permission to use this command.'), ephemeral=True)

@awardachievement.error
async def award_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if not interaction.response.is_done():
        await interaction.response.send_message((f'Use admin commands in <#{ADMIN_CHANNEL_ID}>.' if interaction.channel_id != ADMIN_CHANNEL_ID else 'You need Manage Server permission to use this command.'), ephemeral=True)

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        # The channel check already replied privately. Do not post publicly.
        if not interaction.response.is_done():
            await interaction.response.send_message('This command is unavailable here.', ephemeral=True)
        return
    logging.error('Slash command error: %s', error, exc_info=(type(error), error, error.__traceback__))
    if not interaction.response.is_done():
        try:
            await interaction.response.send_message('Critbot ran into a problem. Check logs/critbot.log.', ephemeral=True)
        except discord.HTTPException:
            logging.warning('Interaction response expired or already acknowledged')

if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('Missing DISCORD_TOKEN in parent Critbot/.env')
    acquire_single_instance()
    init_db()
    logging.info('Critbot channels: public=%s admin=%s', ANNOUNCEMENT_CHANNEL_ID, ADMIN_CHANNEL_ID)
    bot.run(TOKEN)
