"""
╔══════════════════════════════════════════════════════════╗
║              CRAZIE SERVER BOT  ·  main.py               ║
║  Everything lives here — edit freely, no file-hopping.   ║
╠══════════════════════════════════════════════════════════╣
║  SECTIONS (Ctrl+F to jump):                              ║
║  [CONFIG]     — tokens, cooldowns, message pools         ║
║  [DATABASE]   — SQLite schema + helper                   ║
║  [SETUP]      — /setup command                           ║
║  [UTILITY]    — /decide  /vibe  /say                     ║
║  [VOICE]      — /lockvc  /unlockvc  /limitvc             ║
║  [FUN]        — /start  /roast  /lfg                     ║
║  [REMINDERS]  — /remind  /plan                           ║
║  [HIGHLIGHTS] — ⭐ reaction → #highlights                ║
║  [LORE]       — /lore  📖 reaction                       ║
║  [QUOTES]     — /quote  /quotes  💬 reaction             ║
║  [BEEF]       — /beef  leaderboard                       ║
║  [VIBE]       — /vibecheck  /vibereport                  ║
║  [STREAK]     — /streak  daily tracking                  ║
║  [WRAPPED]    — /wrapped  monthly recap                  ║
║  [CLUTCH]     — /clutch  Clutch Mode VC watcher          ║
║  [MODERATION] — spam detection                           ║
║  [EVENTS]     — on_member_join  on_message               ║
║  [REACTIONS]  — raw reaction router                      ║
║  [BOT]        — bot class + entry point                  ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import os
import random
import re
import sys
from collections import defaultdict, deque
from datetime import date, datetime, timedelta

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────
# [CONFIG]  ·  Change these to tune bot behaviour
# ─────────────────────────────────────────────────────────

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

HIGHLIGHT_STAR_THRESHOLD = 1        # Stars needed before a message hits #highlights
ROAST_COOLDOWN_SECONDS   = 30       # Seconds between roasts per user
DECIDE_COOLDOWN_SECONDS  = 10       # Seconds between /decide uses per user
SPAM_MESSAGE_THRESHOLD   = 5        # Messages within window that trigger spam warning
SPAM_TIME_WINDOW_SECONDS = 5        # Rolling window (seconds) for spam detection
CLUTCH_COOLDOWN_MINUTES  = 15       # Min wait between Clutch Mode pings per channel
LFG_EXPIRY_MINUTES       = 30       # Minutes before an unfilled LFG lobby expires

VIBE_MESSAGES = [
    "we eating good tonight 🔥",
    "crazie hours activated",
    "the vibe is immaculate rn",
    "locked in, no cap",
    "we different fr fr",
    "running it up as always",
    "the squad is undefeated",
    "built different, can't relate",
    "W server, W people, W vibes",
    "no bad days in this server",
]

ROAST_MESSAGES = [
    "{target} really said 'I have good opinions' then opened their mouth 💀",
    "{target} is the reason they put instructions on shampoo bottles",
    "bro {target} googles how to google things",
    "{target}'s WiFi password is probably 'password123'",
    "{target} brings a spoon to a knife fight",
    "{target} thinks WiFi is spelled 'wyfy'",
    "when {target} was born the doctor slapped them and they asked 'why'",
    "{target} is 30% decisions, 70% regret",
    "{target}'s search history is a cry for help",
    "{target} has a participation trophy collection fr",
]

CLUTCH_MESSAGES = [
    "bro {lonely} is alone in VC… who's gonna pull up?",
    "{lonely} is holding down the VC solo rn, someone roll through",
    "{lonely} is just vibing alone in VC, don't leave them hanging",
    "VC check: {lonely} is in there all by themselves 💀 {pinged} pull up",
    "{lonely} deployed solo mode in VC, someone rescue them",
]


# ─────────────────────────────────────────────────────────
# [DATABASE]  ·  SQLite via aiosqlite — zero config
# ─────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "storage", "csb.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


async def init_db():
    """Create all tables on first run. Safe to call every startup."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS highlights (
                message_id INTEGER PRIMARY KEY,
                guild_id   INTEGER,
                channel_id INTEGER,
                author_id  INTEGER,
                content    TEXT,
                jump_url   TEXT,
                posted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER,
                channel_id INTEGER,
                user_id    INTEGER,
                message    TEXT,
                trigger_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS lore (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER,
                author_id  INTEGER,
                target_id  INTEGER,
                content    TEXT,
                tags       TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS quotes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER,
                message_id INTEGER UNIQUE,
                author_id  INTEGER,
                content    TEXT,
                jump_url   TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS beef (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     INTEGER,
                initiator_id INTEGER,
                target_id    INTEGER,
                reason       TEXT,
                resolved     INTEGER DEFAULT 0,
                winner_id    INTEGER,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS vibe_checks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER,
                user_id    INTEGER,
                score      INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS streaks (
                guild_id         INTEGER PRIMARY KEY,
                current_streak   INTEGER DEFAULT 0,
                last_active_date TEXT,
                longest_streak   INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      INTEGER,
                user_id       INTEGER,
                activity_type TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS lfg_lobbies (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER,
                channel_id INTEGER,
                message_id INTEGER,
                creator_id INTEGER,
                game       TEXT,
                size       INTEGER,
                members    TEXT DEFAULT '[]',
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS clutch_opt_in (
                guild_id INTEGER,
                user_id  INTEGER,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS clutch_cooldown (
                guild_id   INTEGER,
                channel_id INTEGER,
                last_ping  TIMESTAMP,
                PRIMARY KEY (guild_id, channel_id)
            );
            CREATE TABLE IF NOT EXISTS decide_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER,
                options    TEXT,
                result     TEXT,
                decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()


def get_db():
    """Return an async context manager for the SQLite database."""
    return aiosqlite.connect(DB_PATH)


# ─────────────────────────────────────────────────────────
# [SETUP]  ·  /setup — one command, full server structure
# ─────────────────────────────────────────────────────────

class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Initialize a clean server structure in under 30 seconds")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        await interaction.followup.send("⚙️ Setting up your server…", ephemeral=True)

        core_role = discord.utils.get(guild.roles, name="Core")
        if not core_role:
            core_role = await guild.create_role(name="Core", color=discord.Color.purple(), reason="CSB Setup")

        default_ow = {
            guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            core_role:          discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        core_only_ow = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            core_role:          discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        voice_ow = {
            guild.default_role: discord.PermissionOverwrite(connect=True, speak=True, view_channel=True),
            core_role:          discord.PermissionOverwrite(connect=True, speak=True, view_channel=True, move_members=True),
        }
        existing = [c.name for c in guild.categories]

        if "Hangout" not in existing:
            cat = await guild.create_category("Hangout")
            for name in ["general", "highlights", "beef-log", "status"]:
                await guild.create_text_channel(name, category=cat, overwrites=default_ow)

        if "Voice" not in existing:
            cat = await guild.create_category("Voice")
            for name in ["Main VC", "Chill VC", "Game VC"]:
                await guild.create_voice_channel(name, category=cat, overwrites=voice_ow)

        if "Core" not in existing:
            cat = await guild.create_category("Core", overwrites=core_only_ow)
            await guild.create_text_channel("core-chat", category=cat, overwrites=core_only_ow)
            await guild.create_text_channel("announcements", category=cat, overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                core_role:          discord.PermissionOverwrite(read_messages=True, send_messages=True),
            })

        if "System" not in existing:
            cat = await guild.create_category("System", overwrites=core_only_ow)
            await guild.create_text_channel("bot-logs", category=cat, overwrites=core_only_ow)

        embed = discord.Embed(title="✅ Server Setup Complete", color=discord.Color.green())
        embed.add_field(name="Categories", value="Hangout · Voice · Core · System", inline=False)
        embed.add_field(name="Role Created", value="Core (purple) — assign to your inner circle", inline=False)
        embed.set_footer(text="Run /setup again to add missing channels. Existing ones won't be touched.")
        await interaction.followup.send(embed=embed, ephemeral=True)


# ─────────────────────────────────────────────────────────
# [UTILITY]  ·  /decide  /vibe  /say
# ─────────────────────────────────────────────────────────

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.decide_cooldowns = {}

    @app_commands.command(name="decide", description="Pick randomly from 2–10 options — no more 20-minute debates")
    @app_commands.describe(
        option1="First option", option2="Second option",
        option3="3rd (opt)", option4="4th (opt)", option5="5th (opt)",
        option6="6th (opt)", option7="7th (opt)", option8="8th (opt)",
        option9="9th (opt)", option10="10th (opt)",
    )
    async def decide(self, interaction: discord.Interaction,
                     option1: str, option2: str,
                     option3: str = None, option4: str = None,
                     option5: str = None, option6: str = None,
                     option7: str = None, option8: str = None,
                     option9: str = None, option10: str = None):
        uid = interaction.user.id
        now = datetime.utcnow().timestamp()
        if uid in self.decide_cooldowns:
            elapsed = now - self.decide_cooldowns[uid]
            if elapsed < DECIDE_COOLDOWN_SECONDS:
                await interaction.response.send_message(
                    f"⏳ Chill — decide again in {int(DECIDE_COOLDOWN_SECONDS - elapsed)}s.", ephemeral=True)
                return

        options = [o for o in [option1, option2, option3, option4, option5,
                                option6, option7, option8, option9, option10] if o]
        result = random.choice(options)
        self.decide_cooldowns[uid] = now

        async with get_db() as db:
            await db.execute(
                "INSERT INTO decide_log (guild_id, options, result, decided_at) VALUES (?, ?, ?, ?)",
                (interaction.guild_id, json.dumps(options), result, datetime.utcnow()))
            await db.commit()

        embed = discord.Embed(title="🎲 The Bot Has Spoken", color=discord.Color.purple())
        embed.add_field(name="Options",  value=" · ".join(options), inline=False)
        embed.add_field(name="Decision", value=f"**{result}**",    inline=False)
        embed.set_footer(text=f"Decided by {interaction.user.display_name} • No take-backs.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="vibe", description="Get a random Crazie vibe check")
    async def vibe(self, interaction: discord.Interaction):
        embed = discord.Embed(description=f"**{random.choice(VIBE_MESSAGES)}**", color=discord.Color.og_blurple())
        embed.set_footer(text="Crazie Server Bot · vibe certified")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="say", description="Make the bot say something")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(message="What should the bot say?")
    async def say(self, interaction: discord.Interaction, message: str):
        await interaction.response.send_message("✅ Sent.", ephemeral=True)
        await interaction.channel.send(message)


# ─────────────────────────────────────────────────────────
# [VOICE]  ·  /lockvc  /unlockvc  /limitvc
# ─────────────────────────────────────────────────────────

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _is_core_or_owner(self, interaction: discord.Interaction) -> bool:
        core = discord.utils.get(interaction.guild.roles, name="Core")
        return (interaction.user == interaction.guild.owner or
                (core and core in interaction.user.roles))

    @app_commands.command(name="lockvc", description="Lock all voice channels — Core/Owner only")
    async def lockvc(self, interaction: discord.Interaction):
        if not self._is_core_or_owner(interaction):
            await interaction.response.send_message("🔒 Core/Owner only.", ephemeral=True); return
        locked = []
        for ch in interaction.guild.voice_channels:
            await ch.set_permissions(interaction.guild.default_role, connect=False)
            locked.append(ch.name)
        embed = discord.Embed(title="🔒 Voice Channels Locked",
                              description=", ".join(locked), color=discord.Color.red())
        embed.set_footer(text=f"Locked by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unlockvc", description="Unlock all voice channels — Core/Owner only")
    async def unlockvc(self, interaction: discord.Interaction):
        if not self._is_core_or_owner(interaction):
            await interaction.response.send_message("🔓 Core/Owner only.", ephemeral=True); return
        unlocked = []
        for ch in interaction.guild.voice_channels:
            await ch.set_permissions(interaction.guild.default_role, connect=True)
            unlocked.append(ch.name)
        embed = discord.Embed(title="🔓 Voice Channels Unlocked",
                              description=", ".join(unlocked), color=discord.Color.green())
        embed.set_footer(text=f"Unlocked by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="limitvc", description="Set member limit on a VC — Core/Owner only")
    @app_commands.describe(limit="0–99 (0 = no limit)", channel="Target VC (defaults to your current one)")
    async def limitvc(self, interaction: discord.Interaction, limit: int, channel: discord.VoiceChannel = None):
        if not self._is_core_or_owner(interaction):
            await interaction.response.send_message("Core/Owner only.", ephemeral=True); return
        target = channel or (interaction.user.voice.channel if interaction.user.voice else None)
        if not target:
            await interaction.response.send_message("Join a VC or specify one.", ephemeral=True); return
        if not 0 <= limit <= 99:
            await interaction.response.send_message("Limit must be 0–99.", ephemeral=True); return
        await target.edit(user_limit=limit)
        desc = "No limit" if limit == 0 else f"{limit} members max"
        embed = discord.Embed(title="🎚️ VC Limit Updated",
                              description=f"**{target.name}** → {desc}", color=discord.Color.blue())
        embed.set_footer(text=f"Set by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────
# [FUN]  ·  /start  /roast  /lfg
# ─────────────────────────────────────────────────────────

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.roast_cooldowns = {}

    @app_commands.command(name="start", description="Kick off a session — kills the 'who's gonna initiate' paralysis")
    @app_commands.describe(activity="Activity type", ping="Ping @here?")
    @app_commands.choices(activity=[
        app_commands.Choice(name="Game Night 🎮",  value="game night"),
        app_commands.Choice(name="Movie Night 🎬", value="movie night"),
        app_commands.Choice(name="Chill 😌",       value="chill"),
        app_commands.Choice(name="Custom",         value="custom"),
    ])
    async def start(self, interaction: discord.Interaction,
                    activity: str, ping: bool = False, custom: str = None):
        label = custom if (activity == "custom" and custom) else activity
        emoji = {"game night": "🎮", "movie night": "🎬", "chill": "😌"}.get(activity, "🔥")
        vc = next((v for v in interaction.guild.voice_channels
                   if "main" in v.name.lower() or "general" in v.name.lower()),
                  interaction.guild.voice_channels[0] if interaction.guild.voice_channels else None)

        embed = discord.Embed(title=f"{emoji} {label.title()} — LET'S GO",
                              description=f"**{interaction.user.display_name}** is starting. Who's in?",
                              color=discord.Color.orange())
        if vc:
            embed.add_field(name="Suggested VC", value=vc.mention, inline=True)
        embed.add_field(name="Activity", value=label.title(), inline=True)
        embed.set_footer(text="React ✅ to join or just pull up to VC")

        await interaction.response.send_message(content="@here" if ping else "", embed=embed)
        msg = await interaction.original_response()
        await msg.add_reaction("✅")

    @app_commands.command(name="roast", description="Roast a member — opt-in fun only")
    @app_commands.describe(target="Who's getting roasted?")
    async def roast(self, interaction: discord.Interaction, target: discord.Member):
        uid = interaction.user.id
        now = datetime.utcnow().timestamp()
        if uid in self.roast_cooldowns:
            elapsed = now - self.roast_cooldowns[uid]
            if elapsed < ROAST_COOLDOWN_SECONDS:
                await interaction.response.send_message(
                    f"⏳ Cool down — {int(ROAST_COOLDOWN_SECONDS - elapsed)}s left.", ephemeral=True); return
        if target.id == self.bot.user.id:
            await interaction.response.send_message("I roast. I don't get roasted. 😤", ephemeral=True); return
        self.roast_cooldowns[uid] = now
        embed = discord.Embed(description=f"🔥 {random.choice(ROAST_MESSAGES).format(target=target.display_name)}",
                              color=discord.Color.red())
        embed.set_footer(text=f"Requested by {interaction.user.display_name} · opt-in humor only")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="lfg", description="Looking for group — no more dead 'who's down?' threads")
    @app_commands.describe(game="What game?", size="How many needed? (2–20)")
    async def lfg(self, interaction: discord.Interaction, game: str, size: int):
        if not 2 <= size <= 20:
            await interaction.response.send_message("Size must be 2–20.", ephemeral=True); return

        expires_at = datetime.utcnow() + timedelta(minutes=LFG_EXPIRY_MINUTES)
        members = [interaction.user.id]

        embed = discord.Embed(title=f"🎮 LFG — {game}", color=discord.Color.blue())
        embed.add_field(name="Game",    value=game,                                    inline=True)
        embed.add_field(name="Spots",   value=f"1/{size}",                             inline=True)
        embed.add_field(name="Players", value=interaction.user.mention,                inline=False)
        embed.add_field(name="Expires", value=f"<t:{int(expires_at.timestamp())}:R>",  inline=False)
        embed.set_footer(text="React ✅ to join this lobby")

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        await msg.add_reaction("✅")

        async with get_db() as db:
            await db.execute(
                "INSERT INTO lfg_lobbies (guild_id,channel_id,message_id,creator_id,game,size,members,expires_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (interaction.guild_id, interaction.channel_id, msg.id,
                 interaction.user.id, game, size, json.dumps(members), expires_at))
            await db.commit()

        async def expire():
            await asyncio.sleep(LFG_EXPIRY_MINUTES * 60)
            async with get_db() as db:
                async with db.execute("SELECT id FROM lfg_lobbies WHERE message_id=?", (msg.id,)) as cur:
                    row = await cur.fetchone()
                if row:
                    await db.execute("DELETE FROM lfg_lobbies WHERE message_id=?", (msg.id,))
                    await db.commit()
                    try:
                        await msg.edit(embed=discord.Embed(
                            title=f"⏰ LFG Expired — {game}",
                            description="Lobby didn't fill in time.",
                            color=discord.Color.greyple()))
                    except Exception:
                        pass

        asyncio.create_task(expire())


# ─────────────────────────────────────────────────────────
# [REMINDERS]  ·  /remind  /plan
# ─────────────────────────────────────────────────────────

def _parse_time(time_str: str):
    """Parse '30m', '2h', '1h30m' → seconds. Returns None on bad input."""
    m = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?', time_str.strip().lower())
    if not m or not any(m.groups()):
        return None
    total = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60
    return total if total > 0 else None


class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _fire(self, channel_id, user_id, message, reminder_id, delay):
        await asyncio.sleep(delay)
        ch = self.bot.get_channel(channel_id)
        if ch:
            u = self.bot.get_user(user_id)
            embed = discord.Embed(title="⏰ Reminder", description=message, color=discord.Color.yellow())
            embed.set_footer(text="Set via /remind")
            await ch.send(content=u.mention if u else f"<@{user_id}>", embed=embed)
        async with get_db() as db:
            await db.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
            await db.commit()

    @app_commands.command(name="remind", description="Set a reminder — 30m / 2h / 1h30m format")
    @app_commands.describe(time="When (e.g. 30m, 2h, 1h30m)", message="What to remind you about")
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        secs = _parse_time(time)
        if not secs:
            await interaction.response.send_message("Use `30m`, `2h`, or `1h30m`.", ephemeral=True); return
        trigger = datetime.utcnow() + timedelta(seconds=secs)
        async with get_db() as db:
            cur = await db.execute(
                "INSERT INTO reminders (guild_id,channel_id,user_id,message,trigger_at) VALUES (?,?,?,?,?)",
                (interaction.guild_id, interaction.channel_id, interaction.user.id, message, trigger))
            await db.commit()
            rid = cur.lastrowid
        asyncio.create_task(self._fire(interaction.channel_id, interaction.user.id, message, rid, secs))
        embed = discord.Embed(title="✅ Reminder Set", description=f"I'll remind you in **{time}**",
                              color=discord.Color.green())
        embed.add_field(name="Message", value=message)
        embed.add_field(name="When",    value=f"<t:{int(trigger.timestamp())}:R>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="plan", description="Plan a group activity with a shared reminder")
    @app_commands.describe(time="When (e.g. 30m, 2h)", activity="What's happening?")
    async def plan(self, interaction: discord.Interaction, time: str, activity: str):
        secs = _parse_time(time)
        if not secs:
            await interaction.response.send_message("Use `30m`, `2h`, or `1h30m`.", ephemeral=True); return
        trigger = datetime.utcnow() + timedelta(seconds=secs)
        async with get_db() as db:
            cur = await db.execute(
                "INSERT INTO reminders (guild_id,channel_id,user_id,message,trigger_at) VALUES (?,?,?,?,?)",
                (interaction.guild_id, interaction.channel_id, interaction.user.id, activity, trigger))
            await db.commit()
            rid = cur.lastrowid
        embed = discord.Embed(title="📅 Activity Planned",
                              description=f"**{activity}** starts in **{time}**", color=discord.Color.blue())
        embed.add_field(name="Scheduled by", value=interaction.user.mention)
        embed.add_field(name="When",         value=f"<t:{int(trigger.timestamp())}:R>")
        embed.set_footer(text="I'll ping here when it's time.")
        await interaction.response.send_message(embed=embed)
        asyncio.create_task(
            self._fire(interaction.channel_id, interaction.user.id, f"🔔 Time for **{activity}**!", rid, secs))


# ─────────────────────────────────────────────────────────
# [HIGHLIGHTS]  ·  ⭐ reaction → #highlights  +  /highlights
# ─────────────────────────────────────────────────────────

class Highlights(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def post_highlight(self, message: discord.Message):
        async with get_db() as db:
            async with db.execute("SELECT message_id FROM highlights WHERE message_id=?",
                                  (message.id,)) as cur:
                if await cur.fetchone():
                    return
        ch = discord.utils.get(message.guild.text_channels, name="highlights")
        if not ch:
            return
        embed = discord.Embed(description=message.content or "*[non-text content]*",
                              color=discord.Color.gold(), timestamp=message.created_at)
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Source",  value=f"[Jump]({message.jump_url})", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention,       inline=True)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        embed.set_footer(text="⭐ Highlight")
        await ch.send(embed=embed)
        async with get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO highlights (message_id,guild_id,channel_id,author_id,content,jump_url)"
                " VALUES (?,?,?,?,?,?)",
                (message.id, message.guild.id, message.channel.id,
                 message.author.id, message.content, message.jump_url))
            await db.commit()

    @app_commands.command(name="highlights", description="See recent server highlights")
    async def highlights_cmd(self, interaction: discord.Interaction):
        async with get_db() as db:
            async with db.execute(
                "SELECT content,jump_url,posted_at FROM highlights WHERE guild_id=?"
                " ORDER BY posted_at DESC LIMIT 5", (interaction.guild_id,)) as cur:
                rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message("No highlights yet. React ⭐ to start!", ephemeral=True); return
        embed = discord.Embed(title="⭐ Recent Highlights", color=discord.Color.gold())
        for content, url, _ in rows:
            snip = (content[:80] + "…") if content and len(content) > 80 else (content or "[media]")
            embed.add_field(name=snip, value=f"[Jump]({url})", inline=False)
        await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────
# [LORE]  ·  /lore  +  📖 reaction handler (called from Reactions)
# ─────────────────────────────────────────────────────────

class Lore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="lore", description="Access the server lore archive — inside jokes, bits, moments")
    @app_commands.describe(action="What to do", text="Lore text (for 'add')", member="Filter by member")
    @app_commands.choices(action=[
        app_commands.Choice(name="Random lore entry", value="random"),
        app_commands.Choice(name="Add lore entry",    value="add"),
        app_commands.Choice(name="List recent lore",  value="list"),
    ])
    async def lore(self, interaction: discord.Interaction,
                   action: str = "random", text: str = None, member: discord.Member = None):
        if action == "add":
            if not text:
                await interaction.response.send_message("Provide text with the `text` option.", ephemeral=True); return
            async with get_db() as db:
                await db.execute("INSERT INTO lore (guild_id,author_id,target_id,content) VALUES (?,?,?,?)",
                                 (interaction.guild_id, interaction.user.id,
                                  member.id if member else None, text))
                await db.commit()
            embed = discord.Embed(title="📖 Lore Added", description=text, color=discord.Color.purple())
            embed.set_footer(text=f"Logged by {interaction.user.display_name}")
            await interaction.response.send_message(embed=embed)

        elif action == "random":
            async with get_db() as db:
                q = ("SELECT content,author_id,created_at FROM lore WHERE guild_id=?"
                     + (" AND target_id=?" if member else "") + " ORDER BY RANDOM() LIMIT 1")
                args = (interaction.guild_id, member.id) if member else (interaction.guild_id,)
                async with db.execute(q, args) as cur:
                    row = await cur.fetchone()
            if not row:
                await interaction.response.send_message(
                    "No lore yet. React 📖 or use `/lore add`.", ephemeral=True); return
            content, author_id, created_at = row
            author = interaction.guild.get_member(author_id)
            embed = discord.Embed(title="📖 Server Lore", description=content, color=discord.Color.purple())
            embed.set_footer(text=f"Logged by {author.display_name if author else 'Unknown'}"
                                  f" · {str(created_at)[:10]}")
            await interaction.response.send_message(embed=embed)

        elif action == "list":
            async with get_db() as db:
                async with db.execute(
                    "SELECT content,author_id,created_at FROM lore WHERE guild_id=?"
                    " ORDER BY created_at DESC LIMIT 8", (interaction.guild_id,)) as cur:
                    rows = await cur.fetchall()
            if not rows:
                await interaction.response.send_message("No lore entries yet.", ephemeral=True); return
            embed = discord.Embed(title="📖 Recent Lore", color=discord.Color.purple())
            for content, author_id, created_at in rows:
                author = interaction.guild.get_member(author_id)
                snip = (content[:60] + "…") if len(content) > 60 else content
                embed.add_field(name=snip,
                                value=f"by {author.display_name if author else 'Unknown'}"
                                      f" · {str(created_at)[:10]}", inline=False)
            await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────
# [QUOTES]  ·  /quote  /quotes  +  💬 reaction handler
# ─────────────────────────────────────────────────────────

class Quotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="quote", description="Pull a saved quote from the archive")
    @app_commands.describe(member="Get a quote from a specific person")
    async def quote(self, interaction: discord.Interaction, member: discord.Member = None):
        async with get_db() as db:
            q = ("SELECT content,author_id,jump_url,created_at FROM quotes WHERE guild_id=?"
                 + (" AND author_id=?" if member else "") + " ORDER BY RANDOM() LIMIT 1")
            args = (interaction.guild_id, member.id) if member else (interaction.guild_id,)
            async with db.execute(q, args) as cur:
                row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(
                f"No quotes for {member.display_name} yet." if member
                else "No quotes yet. React 💬 to save one.", ephemeral=True); return
        content, author_id, jump_url, created_at = row
        author = interaction.guild.get_member(author_id)
        embed = discord.Embed(description=f'"{content}"', color=discord.Color.teal())
        embed.set_author(name=author.display_name if author else "Unknown",
                         icon_url=author.display_avatar.url if author else None)
        if jump_url:
            embed.add_field(name="Source", value=f"[Jump to original]({jump_url})")
        embed.set_footer(text=f"Saved · {str(created_at)[:10]}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quotes", description="List recent saved quotes")
    async def quotes_list(self, interaction: discord.Interaction):
        async with get_db() as db:
            async with db.execute(
                "SELECT content,author_id,created_at FROM quotes WHERE guild_id=?"
                " ORDER BY created_at DESC LIMIT 8", (interaction.guild_id,)) as cur:
                rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message("No quotes yet. React 💬 to start.", ephemeral=True); return
        embed = discord.Embed(title="💬 Quote Archive", color=discord.Color.teal())
        for content, author_id, _ in rows:
            author = interaction.guild.get_member(author_id)
            snip = (content[:60] + "…") if len(content) > 60 else content
            embed.add_field(name=f'"{snip}"',
                            value=f"— {author.display_name if author else 'Unknown'}", inline=False)
        await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────
# [BEEF]  ·  /beef  start / resolve / leaderboard
# ─────────────────────────────────────────────────────────

class Beef(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="beef", description="Start or resolve a beef — opt-in rivalry, pure comedy")
    @app_commands.describe(action="Action", member="Who's the beef with?", reason="What's it about?")
    @app_commands.choices(action=[
        app_commands.Choice(name="Start beef",   value="start"),
        app_commands.Choice(name="Resolve beef", value="resolve"),
        app_commands.Choice(name="Leaderboard",  value="leaderboard"),
    ])
    async def beef(self, interaction: discord.Interaction,
                   action: str, member: discord.Member = None, reason: str = None):
        if action == "start":
            if not member:
                await interaction.response.send_message("Pick someone to beef with.", ephemeral=True); return
            if member.id == interaction.user.id:
                await interaction.response.send_message("Can't beef yourself 💀", ephemeral=True); return
            async with get_db() as db:
                async with db.execute(
                    "SELECT id FROM beef WHERE guild_id=? AND initiator_id=? AND target_id=? AND resolved=0",
                    (interaction.guild_id, interaction.user.id, member.id)) as cur:
                    if await cur.fetchone():
                        await interaction.response.send_message(
                            f"Already have open beef with {member.display_name}.", ephemeral=True); return
                cur = await db.execute(
                    "INSERT INTO beef (guild_id,initiator_id,target_id,reason) VALUES (?,?,?,?)",
                    (interaction.guild_id, interaction.user.id, member.id, reason or "no reason given"))
                await db.commit()
                beef_id = cur.lastrowid
            embed = discord.Embed(title="🥩 NEW BEEF ALERT", color=discord.Color.red())
            embed.add_field(name="Initiator", value=interaction.user.mention, inline=True)
            embed.add_field(name="Target",    value=member.mention,            inline=True)
            embed.add_field(name="Reason",    value=reason or "no reason given", inline=False)
            embed.add_field(name="Beef ID",   value=f"#{beef_id}",             inline=True)
            embed.set_footer(text="React 🏆 to vote winner · 🤝 to call truce")
            await interaction.response.send_message(embed=embed)
            msg = await interaction.original_response()
            await msg.add_reaction("🏆")
            await msg.add_reaction("🤝")
            log_ch = discord.utils.get(interaction.guild.text_channels, name="beef-log")
            if log_ch and log_ch.id != interaction.channel_id:
                await log_ch.send(embed=embed)

        elif action == "resolve":
            if not member:
                await interaction.response.send_message("Specify who the beef was with.", ephemeral=True); return
            async with get_db() as db:
                async with db.execute(
                    "SELECT id FROM beef WHERE guild_id=? AND resolved=0 AND"
                    " ((initiator_id=? AND target_id=?) OR (initiator_id=? AND target_id=?))",
                    (interaction.guild_id, interaction.user.id, member.id, member.id, interaction.user.id)) as cur:
                    row = await cur.fetchone()
                if not row:
                    await interaction.response.send_message(f"No active beef with {member.display_name}.", ephemeral=True); return
                await db.execute("UPDATE beef SET resolved=1 WHERE id=?", (row[0],))
                await db.commit()
            embed = discord.Embed(title="🤝 Beef Resolved",
                                  description=f"{interaction.user.mention} and {member.mention} squashed it.",
                                  color=discord.Color.green())
            await interaction.response.send_message(embed=embed)

        elif action == "leaderboard":
            async with get_db() as db:
                async with db.execute(
                    "SELECT initiator_id, COUNT(*) cnt FROM beef WHERE guild_id=?"
                    " GROUP BY initiator_id ORDER BY cnt DESC LIMIT 10", (interaction.guild_id,)) as cur:
                    rows = await cur.fetchall()
            if not rows:
                await interaction.response.send_message("No beefs yet. Stay peaceful… or don't.", ephemeral=True); return
            embed = discord.Embed(title="🥩 Beef Leaderboard", color=discord.Color.red())
            for i, (uid, cnt) in enumerate(rows, 1):
                m = interaction.guild.get_member(uid)
                embed.add_field(name=f"#{i} {m.display_name if m else uid}",
                                value=f"{cnt} beef(s) started", inline=False)
            await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────
# [VIBE]  ·  /vibecheck  /vibereport
# ─────────────────────────────────────────────────────────

class VibeCheck(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="vibecheck", description="Rate the group's energy — anonymous 1–5 daily poll")
    @app_commands.describe(score="1 (dead) to 5 (peak)")
    async def vibecheck(self, interaction: discord.Interaction, score: int):
        if not 1 <= score <= 5:
            await interaction.response.send_message("Score must be 1–5.", ephemeral=True); return
        today = datetime.utcnow().date().isoformat()
        async with get_db() as db:
            async with db.execute(
                "SELECT id FROM vibe_checks WHERE guild_id=? AND user_id=? AND DATE(created_at)=?",
                (interaction.guild_id, interaction.user.id, today)) as cur:
                if await cur.fetchone():
                    await interaction.response.send_message(
                        "Already submitted today. Come back tomorrow.", ephemeral=True); return
            await db.execute("INSERT INTO vibe_checks (guild_id,user_id,score) VALUES (?,?,?)",
                             (interaction.guild_id, interaction.user.id, score))
            await db.commit()
            async with db.execute(
                "SELECT AVG(score), COUNT(*) FROM vibe_checks WHERE guild_id=? AND DATE(created_at)=?",
                (interaction.guild_id, today)) as cur:
                avg, count = await cur.fetchone()
        bars = "█" * score + "░" * (5 - score)
        embed = discord.Embed(title="📊 Vibe Check Submitted", color=discord.Color.purple())
        embed.add_field(name="Your Score",           value=f"{bars} ({score}/5)", inline=False)
        embed.add_field(name="Server Average Today", value=f"{avg:.1f}/5 ({count} responses)", inline=False)
        embed.set_footer(text="Anonymous · aggregate only")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="vibereport", description="See this week's vibe report")
    async def vibereport(self, interaction: discord.Interaction):
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        async with get_db() as db:
            async with db.execute(
                "SELECT DATE(created_at) day, AVG(score) avg, COUNT(*) cnt"
                " FROM vibe_checks WHERE guild_id=? AND created_at>=?"
                " GROUP BY day ORDER BY day", (interaction.guild_id, week_ago)) as cur:
                rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message(
                "No vibe data this week. Use `/vibecheck` to start.", ephemeral=True); return
        embed = discord.Embed(title="📈 Weekly Vibe Report", color=discord.Color.purple())
        for day, avg, cnt in rows:
            bars = "█" * round(avg) + "░" * (5 - round(avg))
            embed.add_field(name=day, value=f"{bars} {avg:.1f}/5 ({cnt} votes)", inline=False)
        overall = sum(r[1] for r in rows) / len(rows)
        embed.set_footer(text=f"7-day average: {overall:.1f}/5")
        await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────
# [STREAK]  ·  /streak  +  record_activity() used by events
# ─────────────────────────────────────────────────────────

class Streak(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def record_activity(self, guild_id: int):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        async with get_db() as db:
            async with db.execute(
                "SELECT current_streak,last_active_date,longest_streak FROM streaks WHERE guild_id=?",
                (guild_id,)) as cur:
                row = await cur.fetchone()
            if not row:
                await db.execute(
                    "INSERT INTO streaks (guild_id,current_streak,last_active_date,longest_streak)"
                    " VALUES (?,1,?,1)", (guild_id, today))
                await db.commit()
                return
            current, last, longest = row
            if last == today:
                return
            new_streak = (current + 1) if last == yesterday else 1
            new_longest = max(longest, new_streak)
            await db.execute(
                "UPDATE streaks SET current_streak=?,last_active_date=?,longest_streak=? WHERE guild_id=?",
                (new_streak, today, new_longest, guild_id))
            await db.commit()
            if last not in (today, yesterday) and last and current > 1:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    ch = (discord.utils.get(guild.text_channels, name="general") or
                          discord.utils.get(guild.text_channels, name="status"))
                    if ch:
                        await ch.send(embed=discord.Embed(
                            title="💔 STREAK BROKEN",
                            description=f"The {current}-day streak just ended. Restart it today.",
                            color=discord.Color.red()))

    @app_commands.command(name="streak", description="Check the server's daily activity streak")
    async def streak(self, interaction: discord.Interaction):
        async with get_db() as db:
            async with db.execute(
                "SELECT current_streak,last_active_date,longest_streak FROM streaks WHERE guild_id=?",
                (interaction.guild_id,)) as cur:
                row = await cur.fetchone()
        if not row or row[0] == 0:
            await interaction.response.send_message(
                "No streak yet. Chat or join VC to start one!", ephemeral=True); return
        current, last, longest = row
        alive = last == date.today().isoformat()
        fire = "🔥" * min(current, 10)
        embed = discord.Embed(title="🔥 Server Streak",
                              color=discord.Color.orange() if alive else discord.Color.greyple())
        embed.add_field(name="Current Streak", value=f"{current} day(s) {fire}", inline=True)
        embed.add_field(name="Best Streak",    value=f"{longest} day(s)",         inline=True)
        embed.add_field(name="Last Active",    value=last or "Never",              inline=True)
        embed.set_footer(text="Keep it going." if alive else "⚠️ Streak at risk — talk or jump in VC!")
        await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────
# [WRAPPED]  ·  /wrapped — monthly recap
# ─────────────────────────────────────────────────────────

class Wrapped(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="wrapped", description="Crazie Wrapped — monthly recap for your friend group")
    async def wrapped(self, interaction: discord.Interaction):
        await interaction.response.defer()
        gid      = interaction.guild_id
        month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()

        async with get_db() as db:
            async with db.execute(
                "SELECT user_id, COUNT(*) cnt FROM activity_log"
                " WHERE guild_id=? AND created_at>=? AND activity_type='message'"
                " GROUP BY user_id ORDER BY cnt DESC LIMIT 5", (gid, month_ago)) as cur:
                top_talkers = await cur.fetchall()

            async with db.execute(
                "SELECT COUNT(*) FROM lore WHERE guild_id=? AND created_at>=?", (gid, month_ago)) as cur:
                lore_count = (await cur.fetchone())[0]

            async with db.execute(
                "SELECT COUNT(*) FROM highlights WHERE guild_id=? AND posted_at>=?", (gid, month_ago)) as cur:
                highlight_count = (await cur.fetchone())[0]

            async with db.execute(
                "SELECT author_id, COUNT(*) cnt FROM quotes WHERE guild_id=? AND created_at>=?"
                " GROUP BY author_id ORDER BY cnt DESC LIMIT 1", (gid, month_ago)) as cur:
                top_quoted = await cur.fetchone()

            async with db.execute(
                "SELECT initiator_id, COUNT(*) cnt FROM beef WHERE guild_id=? AND created_at>=?"
                " GROUP BY initiator_id ORDER BY cnt DESC LIMIT 1", (gid, month_ago)) as cur:
                top_beef = await cur.fetchone()

            async with db.execute(
                "SELECT result, COUNT(*) cnt FROM decide_log WHERE guild_id=? AND decided_at>=?"
                " GROUP BY result ORDER BY cnt DESC LIMIT 1", (gid, month_ago)) as cur:
                top_decide = await cur.fetchone()

        now = datetime.utcnow()
        embed = discord.Embed(
            title=f"🎉 Crazie Wrapped — {now.strftime('%B %Y')}",
            description="Your friend group's monthly recap. Spotify Wrapped but make it ours.",
            color=discord.Color.purple())

        if top_talkers:
            lines = []
            for i, (uid, cnt) in enumerate(top_talkers, 1):
                m = interaction.guild.get_member(uid)
                lines.append(f"**#{i}** {m.display_name if m else uid} — {cnt} messages")
            embed.add_field(name="💬 Most Active", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="💬 Most Active", value="No data yet", inline=False)

        embed.add_field(name="📖 Lore Added",        value=str(lore_count),      inline=True)
        embed.add_field(name="⭐ Highlights",         value=str(highlight_count), inline=True)

        if top_quoted:
            m = interaction.guild.get_member(top_quoted[0])
            embed.add_field(name="💬 Most Quoted",
                            value=f"{m.display_name if m else top_quoted[0]} ({top_quoted[1]})", inline=True)
        if top_beef:
            m = interaction.guild.get_member(top_beef[0])
            embed.add_field(name="🥩 Beef King",
                            value=f"{m.display_name if m else top_beef[0]} ({top_beef[1]} beefs)", inline=True)
        if top_decide:
            embed.add_field(name="🎲 Most Decided",  value=top_decide[0],         inline=True)

        embed.set_footer(text=f"Generated {now.strftime('%B %d, %Y')} · Crazie Server Bot")
        await interaction.followup.send(embed=embed)


# ─────────────────────────────────────────────────────────
# [CLUTCH]  ·  /clutch opt-in/out  +  VC watcher logic
# ─────────────────────────────────────────────────────────

class Clutch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="clutch",
                          description="Opt in/out of Clutch Mode — get pinged when someone's alone in VC")
    @app_commands.choices(action=[
        app_commands.Choice(name="Opt in",  value="in"),
        app_commands.Choice(name="Opt out", value="out"),
        app_commands.Choice(name="Status",  value="status"),
    ])
    async def clutch(self, interaction: discord.Interaction, action: str = "status"):
        if action == "in":
            async with get_db() as db:
                await db.execute("INSERT OR IGNORE INTO clutch_opt_in (guild_id,user_id) VALUES (?,?)",
                                 (interaction.guild_id, interaction.user.id))
                await db.commit()
            await interaction.response.send_message(
                "✅ You're in the Clutch pool — you'll be pinged when someone's alone in VC.", ephemeral=True)

        elif action == "out":
            async with get_db() as db:
                await db.execute("DELETE FROM clutch_opt_in WHERE guild_id=? AND user_id=?",
                                 (interaction.guild_id, interaction.user.id))
                await db.commit()
            await interaction.response.send_message("👋 Opted out of Clutch Mode.", ephemeral=True)

        elif action == "status":
            async with get_db() as db:
                async with db.execute("SELECT user_id FROM clutch_opt_in WHERE guild_id=?",
                                      (interaction.guild_id,)) as cur:
                    rows = await cur.fetchall()
            opted = [m for r in rows if (m := interaction.guild.get_member(r[0]))]
            if not opted:
                await interaction.response.send_message(
                    "Nobody opted in yet. Use `/clutch in`.", ephemeral=True); return
            await interaction.response.send_message(
                f"🔔 Clutch pool ({len(opted)}): {', '.join(m.display_name for m in opted)}", ephemeral=True)

    async def check_clutch(self, guild: discord.Guild, channel: discord.VoiceChannel,
                           lone: discord.Member):
        now = datetime.utcnow()
        async with get_db() as db:
            async with db.execute(
                "SELECT last_ping FROM clutch_cooldown WHERE guild_id=? AND channel_id=?",
                (guild.id, channel.id)) as cur:
                row = await cur.fetchone()
        if row and (now - datetime.fromisoformat(row[0])).total_seconds() < CLUTCH_COOLDOWN_MINUTES * 60:
            return

        async with get_db() as db:
            async with db.execute("SELECT user_id FROM clutch_opt_in WHERE guild_id=?",
                                  (guild.id,)) as cur:
                opt_ids = {r[0] for r in await cur.fetchall()}

        eligible = [m for m in guild.members
                    if m.id in opt_ids and m.id != lone.id and not m.bot
                    and m.status != discord.Status.offline
                    and (not m.voice or not m.voice.channel)]
        if not eligible:
            return

        pinged = random.choice(eligible)
        msg = random.choice(CLUTCH_MESSAGES).format(lonely=lone.display_name, pinged=pinged.mention)
        ch = discord.utils.get(guild.text_channels, name="general")
        if ch:
            await ch.send(msg)

        async with get_db() as db:
            await db.execute(
                "INSERT INTO clutch_cooldown (guild_id,channel_id,last_ping) VALUES (?,?,?)"
                " ON CONFLICT(guild_id,channel_id) DO UPDATE SET last_ping=excluded.last_ping",
                (guild.id, channel.id, now.isoformat()))
            await db.commit()


# ─────────────────────────────────────────────────────────
# [MODERATION]  ·  spam detection — invisible unless triggered
# ─────────────────────────────────────────────────────────

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.history  = defaultdict(deque)
        self.warned   = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        key = (message.guild.id, message.author.id)
        now = datetime.utcnow().timestamp()
        q   = self.history[key]
        q.append(now)
        while q and now - q[0] > SPAM_TIME_WINDOW_SECONDS:
            q.popleft()
        if len(q) >= SPAM_MESSAGE_THRESHOLD:
            if key not in self.warned:
                self.warned.add(key)
                try:
                    await message.channel.send(
                        f"{message.author.mention} slow down — that looks like spam.", delete_after=5)
                except Exception:
                    pass
        else:
            self.warned.discard(key)


# ─────────────────────────────────────────────────────────
# [EVENTS]  ·  on_member_join  +  on_message (activity log)
# ─────────────────────────────────────────────────────────

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        role = discord.utils.get(guild.roles, name="Member")
        if role:
            try:
                await member.add_roles(role, reason="Auto-assigned on join")
            except discord.Forbidden:
                pass
        try:
            embed = discord.Embed(
                title=f"Welcome to {guild.name} 👋",
                description=(
                    f"Hey **{member.display_name}**, glad you're here.\n\n"
                    f"Head to **#general** to intro yourself or jump into a VC.\n"
                    f"Try `/vibe` to get a feel, and `/start` to kick something off.\n\n"
                    f"See you in there."),
                color=discord.Color.purple())
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            embed.set_footer(text="Crazie Server Bot · powered by good vibes")
            await member.send(embed=embed)
        except discord.Forbidden:
            pass
        ch = discord.utils.get(guild.text_channels, name="general")
        if ch:
            await ch.send(embed=discord.Embed(
                description=f"**{member.mention}** just pulled up. Say what's good. 👋",
                color=discord.Color.purple()))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        async with get_db() as db:
            await db.execute(
                "INSERT INTO activity_log (guild_id,user_id,activity_type) VALUES (?,?,'message')",
                (message.guild.id, message.author.id))
            await db.commit()
        streak_cog = self.bot.get_cog("Streak")
        if streak_cog:
            await streak_cog.record_activity(message.guild.id)


# ─────────────────────────────────────────────────────────
# [REACTIONS]  ·  routes ⭐ 📖 💬 ✅ + Clutch Mode VC watcher
# ─────────────────────────────────────────────────────────

class Reactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id or not payload.guild_id:
            return
        emoji = str(payload.emoji)
        if   emoji == "⭐": await self._star(payload)
        elif emoji == "📖": await self._lore(payload)
        elif emoji == "💬": await self._quote(payload)
        elif emoji == "✅": await self._lfg_join(payload)

    async def _fetch_msg(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        ch    = guild.get_channel(payload.channel_id)
        try:
            return await ch.fetch_message(payload.message_id), ch
        except Exception:
            return None, None

    async def _star(self, payload):
        msg, _ = await self._fetch_msg(payload)
        if not msg:
            return
        for r in msg.reactions:
            if str(r.emoji) == "⭐" and r.count >= HIGHLIGHT_STAR_THRESHOLD:
                h = self.bot.get_cog("Highlights")
                if h:
                    await h.post_highlight(msg)
                break

    async def _lore(self, payload):
        msg, ch = await self._fetch_msg(payload)
        if not msg or not msg.content:
            return
        async with get_db() as db:
            async with db.execute(
                "SELECT id FROM lore WHERE guild_id=? AND content=? AND author_id=?",
                (payload.guild_id, msg.content, msg.author.id)) as cur:
                if not await cur.fetchone():
                    await db.execute("INSERT INTO lore (guild_id,author_id,content) VALUES (?,?,?)",
                                     (payload.guild_id, msg.author.id, msg.content))
                    await db.commit()
                    try:
                        snip = msg.content[:80] + ("..." if len(msg.content) > 80 else "")
                        await ch.send(f"📖 Lore captured: *\"{snip}\"*", delete_after=5)
                    except Exception:
                        pass

    async def _quote(self, payload):
        msg, ch = await self._fetch_msg(payload)
        if not msg or not msg.content:
            return
        async with get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO quotes (guild_id,message_id,author_id,content,jump_url)"
                " VALUES (?,?,?,?,?)",
                (payload.guild_id, payload.message_id, msg.author.id, msg.content, msg.jump_url))
            await db.commit()
        try:
            await ch.send(f"💬 Quote saved from **{msg.author.display_name}**.", delete_after=4)
        except Exception:
            pass

    async def _lfg_join(self, payload):
        async with get_db() as db:
            async with db.execute(
                "SELECT id,members,size,game,channel_id FROM lfg_lobbies WHERE message_id=?",
                (payload.message_id,)) as cur:
                row = await cur.fetchone()
        if not row:
            return
        lobby_id, members_str, size, game, channel_id = row
        members = json.loads(members_str)
        if payload.user_id in members:
            return
        members.append(payload.user_id)
        guild = self.bot.get_guild(payload.guild_id)
        ch    = guild.get_channel(channel_id)

        if len(members) >= size:
            mentions = " ".join(f"<@{u}>" for u in members)
            embed = discord.Embed(title=f"🎮 Lobby Full — {game}",
                                  description=f"All {size} slots filled. Let's go!\n{mentions}",
                                  color=discord.Color.green())
            try:
                await ch.send(embed=embed)
            except Exception:
                pass
            async with get_db() as db:
                await db.execute("DELETE FROM lfg_lobbies WHERE id=?", (lobby_id,))
                await db.commit()
        else:
            async with get_db() as db:
                await db.execute("UPDATE lfg_lobbies SET members=? WHERE id=?",
                                 (json.dumps(members), lobby_id))
                await db.commit()
            try:
                msg_ch = guild.get_channel(payload.channel_id)
                msg    = await msg_ch.fetch_message(payload.message_id)
                new_embed = discord.Embed(title=f"🎮 LFG — {game}", color=discord.Color.blue())
                new_embed.add_field(name="Game",    value=game,                                    inline=True)
                new_embed.add_field(name="Spots",   value=f"{len(members)}/{size}",                inline=True)
                new_embed.add_field(name="Players", value=" ".join(f"<@{u}>" for u in members),   inline=False)
                new_embed.set_footer(text="React ✅ to join this lobby")
                await msg.edit(embed=new_embed)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        # Clutch Mode: someone is now alone in VC
        if after.channel:
            real = [m for m in after.channel.members if not m.bot]
            if len(real) == 1:
                clutch = self.bot.get_cog("Clutch")
                if clutch:
                    await clutch.check_clutch(member.guild, after.channel, real[0])
        # Streak: joining a VC counts as activity
        if after.channel and not before.channel:
            streak = self.bot.get_cog("Streak")
            if streak:
                await streak.record_activity(member.guild.id)


# ─────────────────────────────────────────────────────────
# [BOT]  ·  bot class + startup + entry point
# ─────────────────────────────────────────────────────────

ALL_COGS = [
    Setup, Utility, Voice, Fun, Reminders, Highlights,
    Lore, Quotes, Beef, VibeCheck, Streak, Wrapped,
    Clutch, Moderation, Events, Reactions,
]


class CrazieBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True   # Privileged — enable in Dev Portal
        intents.members          = True   # Privileged — enable in Dev Portal
        intents.presences        = True   # Privileged — enable in Dev Portal (Clutch Mode)
        intents.reactions        = True
        intents.voice_states     = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await init_db()
        for cog_cls in ALL_COGS:
            await self.add_cog(cog_cls(self))
            print(f"  ✓ {cog_cls.__name__}")
        await self.tree.sync()
        print("Slash commands synced.")

    async def on_ready(self):
        print(f"\n{'='*44}")
        print(f"  Crazie Server Bot · online")
        print(f"  {self.user}  ({self.user.id})")
        print(f"  Guilds: {len(self.guilds)}")
        print(f"{'='*44}\n")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="the server 👀"))


async def main():
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set.")
        sys.exit(1)
    bot = CrazieBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
