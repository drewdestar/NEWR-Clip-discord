"""NEWR Clip — memorable-message highlights, slash commands only.

  /clip add <content> [image]  — submit a clip for staff approval.
      content is either typed text or a Discord message link
      (https://discord.com/channels/<guild>/<channel>/<message>);
      a link is fetched and its message text is clipped, so the
      highlight quotes the original message. NOT voice recording:
      Discord bots cannot reliably record voice from this VM, and
      this bot never claims to.
  /clip list                   — newest approved clips.
  /clip top                    — approved clips ranked by votes.
  /clip random                 — one random approved clip.
  /clip search <query>         — search approved clips by text.
  /clip vote <id>              — vote for an approved clip, once
                                 per user per clip (enforced by the
                                 votes PRIMARY KEY).
  /clip delete <id>            — delete your own clip, or any clip
                                 if staff.
  /clip approve <id>           — staff only: approve a pending clip
                                 and post it to the highlight channel.
  /clip reject <id>            — staff only: reject (delete) a
                                 pending clip.
  /clip setup <channel>        — staff only: set the highlight channel.
  /clip weekly                 — staff only: manually post this
                                 week's highlight (top approved clip
                                 of the last 7 days) to the highlight
                                 channel. The same post also runs
                                 automatically every Monday at 09:00
                                 WIB; one post per guild per ISO week
                                 is enforced in the database, so the
                                 manual command and the loop cannot
                                 double-post the same week.
  /clip leaderboard            — submitters ranked by approved clip
                                 count, then total votes.

Approval queue: a submitted clip is 'pending' and appears NOWHERE
public until staff approve it. Approving posts the clip embed to
the highlight channel and marks it approved; only approved clips
are listed, ranked, searched, voted on, or highlighted. If no
highlight channel is set, approval is refused and the pending
clip is kept, so nothing is approved-but-unposted.

Clips are NOT anonymous (unlike Social's confessions): the
submitter's user ID is stored, shown as the submitter on the
highlight embed, used for /clip delete ownership, and used for
/clip leaderboard. No other user tracking is stored.
"""
from __future__ import annotations

import re
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db
import ui
from staff import is_staff, require_staff

_WIB = ZoneInfo("Asia/Jakarta")
_MAX_LENGTH = 2000
_LINK_RE = re.compile(
    r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/"
    r"(\d+)/(\d+)/(\d+)")


def _preview(text: str, limit: int = 100) -> str:
    one_line = (text or "").replace("\n", " ")
    return one_line[:limit] + ("…" if len(one_line) > limit else "")


def _clip_embed(row) -> discord.Embed:
    """Standard highlight embed for one clip row (must have votes)."""
    fields = [
        ("Votes", f"⭐ {row['votes']}", True),
        ("Submitted by", f"<@{row['submitted_by']}>", True),
    ]
    if row["source_link"]:
        fields.append(("Source", row["source_link"], False))
    if row["original_author_id"] and row["original_author_id"] != row["submitted_by"]:
        fields.append(("Original author", f"<@{row['original_author_id']}>", True))
    embed = ui.make(
        f"📌 Clip #{row['id']}", row["text"], colour=ui.BLURPLE,
        fields=fields, image=row["image_url"])
    return embed


def _list_lines(rows, show_votes: bool = True) -> str:
    lines = []
    for row in rows:
        votes = f" ⭐ {row['votes']}" if show_votes else ""
        lines.append(f"#{row['id']}{votes} — {_preview(row['text'])}")
    return "\n".join(lines)


async def _resolve_channel(bot: commands.Bot, guild: discord.Guild,
                           channel_id: int) -> discord.TextChannel | None:
    channel = guild.get_channel(channel_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        try:
            fetched = await bot.fetch_channel(channel_id)
            channel = fetched if isinstance(fetched, discord.TextChannel) else None
        except Exception:
            channel = None
    return channel


async def _post_weekly(bot: commands.Bot, guild: discord.Guild) -> str:
    """Post this week's highlight if due. Returns a status string:
    'posted', 'already', 'no_channel', 'no_clips', 'channel_missing',
    or 'failed'."""
    week_start = datetime.now(_WIB).strftime("%G-W%V")  # ISO year-week
    if db.weekly_already_posted(guild.id, week_start):
        return "already"
    channel_id = db.get_int_setting(guild.id, "highlight_channel")
    if channel_id is None:
        return "no_channel"
    clip = db.weekly_top(guild.id)
    if clip is None:
        return "no_clips"
    channel = await _resolve_channel(bot, guild, channel_id)
    if channel is None:
        return "channel_missing"
    try:
        await channel.send(
            embed=ui.make(
                "🏆 Clip of the Week",
                f"Top approved clip of the last 7 days:\n\n{clip['text']}",
                colour=ui.GOLD,
                fields=[("Clip", f"Clip #{clip['id']}", True),
                        ("Votes", f"⭐ {clip['votes']}", True),
                        ("Submitted by", f"<@{clip['submitted_by']}>", True)],
                image=clip["image_url"]))
    except Exception:
        return "failed"
    db.mark_weekly_posted(guild.id, week_start, clip["id"])
    return "posted"


class ClipGroup(app_commands.Group):
    """Group for all NEWR Clip commands."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(name="clip", description="Save and highlight memorable messages.")
        self.bot = bot

    async def _guild_only(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=ui.err("Server only", "This command only works inside a server."),
                ephemeral=True)
            return False
        return True

    @app_commands.command(name="add", description="Submit a clip (text or a message link) for staff approval.")
    @app_commands.describe(
        content="Typed text, or a Discord message link to clip that message (max 2000 characters).",
        image="Optional image to attach to your clip (image files only).")
    async def add(self, interaction: discord.Interaction, content: str,
                  image: discord.Attachment | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._guild_only_deferred(interaction):
            return
        guild = interaction.guild
        assert guild is not None
        text = (content or "").strip()
        if not text:
            await interaction.followup.send(
                embed=ui.err("Empty clip", "Your clip cannot be empty."), ephemeral=True)
            return
        if len(text) > _MAX_LENGTH and not _LINK_RE.search(text):
            await interaction.followup.send(
                embed=ui.err("Clip too long", f"Your clip is too long (max {_MAX_LENGTH} characters)."),
                ephemeral=True)
            return
        image_url: str | None = None
        if image is not None:
            if not (image.content_type or "").startswith("image/"):
                await interaction.followup.send(
                    embed=ui.err("Image only", "Only image attachments are accepted for clips."),
                    ephemeral=True)
                return
            image_url = image.url
        source_link: str | None = None
        original_author_id: int | None = None
        match = _LINK_RE.search(text)
        if match:
            # Message link: fetch the original message and clip its text.
            # A link longer than the limit is fine: only the fetched
            # message text is length-checked, not the URL itself.
            _link_guild, channel_id, message_id = (int(g) for g in match.groups())
            try:
                channel = guild.get_channel(channel_id)
                if channel is None or not isinstance(channel, discord.TextChannel):
                    channel = await self.bot.fetch_channel(channel_id)
                fetched = await channel.fetch_message(message_id)  # type: ignore[union-attr]
            except Exception:
                await interaction.followup.send(
                    embed=ui.err("Could not fetch message",
                                 "I could not fetch that message. Check the link, and make "
                                 "sure I can see that channel."),
                    ephemeral=True)
                return
            text = (fetched.content or "").strip()
            if not text and image_url is None:
                # Image-only original message: fall back to its image.
                for att in fetched.attachments:
                    if (att.content_type or "").startswith("image/"):
                        image_url = att.url
                        text = "[image]"
                        break
            if not text:
                await interaction.followup.send(
                    embed=ui.err("Nothing to clip", "That message has no text or image to clip."),
                    ephemeral=True)
                return
            if len(text) > _MAX_LENGTH:
                await interaction.followup.send(
                    embed=ui.err("Message too long", f"That message is too long to clip (max {_MAX_LENGTH} characters)."),
                    ephemeral=True)
                return
            source_link = match.group(0)
            original_author_id = fetched.author.id
        clip_id = db.add_clip(guild.id, interaction.user.id,
                              original_author_id, text, image_url, source_link)
        await interaction.followup.send(
            embed=ui.ok("Clip submitted",
                        f"Clip #{clip_id} has been submitted for staff approval. "
                        "It will appear in the highlight channel once approved."),
            ephemeral=True)

    async def _guild_only_deferred(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.followup.send(
                embed=ui.err("Server only", "This command only works inside a server."),
                ephemeral=True)
            return False
        return True

    @app_commands.command(name="list", description="Show the newest approved clips.")
    async def list_clips(self, interaction: discord.Interaction) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        rows = db.list_approved(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(
                embed=ui.info("No clips yet", "No approved clips yet. Submit one with /clip add."),
                ephemeral=True)
            return
        await interaction.response.send_message(
            embed=ui.info("Approved clips", _list_lines(rows)))

    @app_commands.command(name="top", description="Show approved clips ranked by votes.")
    async def top(self, interaction: discord.Interaction) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        rows = db.top_approved(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(
                embed=ui.info("No clips yet", "No approved clips yet. Submit one with /clip add."),
                ephemeral=True)
            return
        lines = [f"{i}. #{row['id']} ⭐ {row['votes']} — {_preview(row['text'])}"
                 for i, row in enumerate(rows, start=1)]
        await interaction.response.send_message(
            embed=ui.make("🏆 Top clips", "\n".join(lines), colour=ui.GOLD))

    @app_commands.command(name="random", description="Show one random approved clip.")
    async def random_clip(self, interaction: discord.Interaction) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        row = db.random_approved(interaction.guild.id)
        if row is None:
            await interaction.response.send_message(
                embed=ui.info("No clips yet", "No approved clips yet. Submit one with /clip add."),
                ephemeral=True)
            return
        await interaction.response.send_message(embed=_clip_embed(row))

    @app_commands.command(name="search", description="Search approved clips by text.")
    @app_commands.describe(query="Text to search for in approved clips.")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        query = (query or "").strip()
        if not query:
            await interaction.response.send_message(
                embed=ui.err("Empty search", "Enter something to search for."), ephemeral=True)
            return
        rows = db.search_approved(interaction.guild.id, query)
        if not rows:
            await interaction.response.send_message(
                embed=ui.info("No matches", f"No approved clips match '{query}'."),
                ephemeral=True)
            return
        await interaction.response.send_message(
            embed=ui.info(f"Clips matching '{query}'", _list_lines(rows)))

    @app_commands.command(name="vote", description="Vote for an approved clip (once per user per clip).")
    @app_commands.describe(clip_id="Clip ID from /clip list or /clip top.")
    async def vote(self, interaction: discord.Interaction, clip_id: int) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        result = db.vote_clip(clip_id, interaction.guild.id, interaction.user.id)
        if result == "not_found":
            await interaction.response.send_message(
                embed=ui.err("Not found", f"No clip with ID {clip_id}."), ephemeral=True)
        elif result == "not_approved":
            await interaction.response.send_message(
                embed=ui.err("Not approved yet", f"Clip #{clip_id} is still waiting for staff approval and cannot be voted on yet."),
                ephemeral=True)
        elif result == "already":
            await interaction.response.send_message(
                embed=ui.warn("Already voted", f"You have already voted for clip #{clip_id}. Votes count once per user per clip."),
                ephemeral=True)
        else:
            row = db.get_clip(clip_id, interaction.guild.id)
            votes = row["votes"] if row else "?"
            await interaction.response.send_message(
                embed=ui.ok("Vote counted", f"Your vote for clip #{clip_id} was counted. It now has ⭐ {votes}."),
                ephemeral=True)

    @app_commands.command(name="delete", description="Delete your own clip, or any clip if staff.")
    @app_commands.describe(clip_id="Clip ID to delete.")
    async def delete(self, interaction: discord.Interaction, clip_id: int) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        row = db.get_clip(clip_id, interaction.guild.id)
        if row is None:
            await interaction.response.send_message(
                embed=ui.err("Not found", f"No clip with ID {clip_id}."), ephemeral=True)
            return
        is_owner = row["submitted_by"] == interaction.user.id
        staff = isinstance(interaction.user, discord.Member) and is_staff(interaction.user)
        if not (is_owner or staff):
            await interaction.response.send_message(
                embed=ui.err("Not yours", "You can only delete your own clips. Staff can delete any clip."),
                ephemeral=True)
            return
        db.delete_clip(clip_id, interaction.guild.id)
        await interaction.response.send_message(
            embed=ui.ok("Clip deleted", f"Clip #{clip_id} has been deleted."), ephemeral=True)

    @app_commands.command(name="approve", description="Staff only: approve a pending clip and post it to the highlight channel.")
    @app_commands.describe(clip_id="Pending clip ID (see the queue via staff review; pending clips are not listed publicly).")
    async def approve(self, interaction: discord.Interaction, clip_id: int) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        if not await require_staff(interaction):
            return
        row = db.get_clip(clip_id, interaction.guild.id)
        if row is None:
            await interaction.response.send_message(
                embed=ui.err("Not found", f"No clip with ID {clip_id}."), ephemeral=True)
            return
        if row["status"] != "pending":
            await interaction.response.send_message(
                embed=ui.err("Not pending", f"Clip #{clip_id} is not pending (status: {row['status']})."),
                ephemeral=True)
            return
        channel_id = db.get_int_setting(interaction.guild.id, "highlight_channel")
        if channel_id is None:
            await interaction.response.send_message(
                embed=ui.err("No highlight channel",
                             "No highlight channel has been set yet. Run /clip setup first. "
                             "The pending clip was kept."),
                ephemeral=True)
            return
        channel = await _resolve_channel(self.bot, interaction.guild, channel_id)
        if channel is None:
            await interaction.response.send_message(
                embed=ui.err("Channel not found",
                             "The configured highlight channel could not be found. "
                             "Run /clip setup again. The pending clip was kept."),
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            posted = await channel.send(embed=_clip_embed(row))
        except discord.Forbidden:
            await interaction.followup.send(
                embed=ui.err("No permission",
                             "I don't have permission to post in the highlight channel. "
                             "The pending clip was kept."),
                ephemeral=True)
            return
        except Exception:
            await interaction.followup.send(
                embed=ui.err("Posting failed",
                             "Something went wrong while posting. The pending clip was kept."),
                ephemeral=True)
            return
        db.approve_clip(clip_id, interaction.guild.id, channel.id, posted.id)
        await interaction.followup.send(
            embed=ui.ok("Clip approved", f"Clip #{clip_id} approved and posted to {channel.mention}."),
            ephemeral=True)

    @app_commands.command(name="reject", description="Staff only: reject (delete) a pending clip.")
    @app_commands.describe(clip_id="Pending clip ID to reject.")
    async def reject(self, interaction: discord.Interaction, clip_id: int) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        if not await require_staff(interaction):
            return
        row = db.get_clip(clip_id, interaction.guild.id)
        if row is None:
            await interaction.response.send_message(
                embed=ui.err("Not found", f"No clip with ID {clip_id}."), ephemeral=True)
            return
        if row["status"] != "pending":
            await interaction.response.send_message(
                embed=ui.err("Not pending", f"Clip #{clip_id} is not pending (status: {row['status']})."),
                ephemeral=True)
            return
        db.delete_clip(clip_id, interaction.guild.id)
        await interaction.response.send_message(
            embed=ui.ok("Clip rejected", f"Clip #{clip_id} rejected and removed."), ephemeral=True)

    @app_commands.command(name="setup", description="Staff only: set the highlight channel for approved clips and weekly highlights.")
    @app_commands.describe(channel="Channel where approved clips and weekly highlights will be posted.")
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        if not await require_staff(interaction):
            return
        db.set_setting(interaction.guild.id, "highlight_channel", str(channel.id))
        await interaction.response.send_message(
            embed=ui.ok("Highlight channel set", f"Approved clips and weekly highlights will be posted to {channel.mention}."),
            ephemeral=True)

    @app_commands.command(name="weekly", description="Staff only: post this week's highlight to the highlight channel now.")
    async def weekly(self, interaction: discord.Interaction) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        if not await require_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        result = await _post_weekly(self.bot, interaction.guild)
        messages = {
            "posted": "Weekly highlight posted to the highlight channel.",
            "already": "This week's highlight has already been posted.",
            "no_channel": "No highlight channel has been set yet. Run /clip setup first.",
            "no_clips": "No approved clips from the last 7 days to highlight.",
            "channel_missing": "The configured highlight channel could not be found. Run /clip setup again.",
            "failed": "Posting failed. Check my permissions in the highlight channel and try again.",
        }
        if result == "posted":
            await interaction.followup.send(embed=ui.ok("Weekly highlight", messages[result]), ephemeral=True)
        elif result == "already":
            await interaction.followup.send(embed=ui.info("Already posted", messages[result]), ephemeral=True)
        else:
            await interaction.followup.send(embed=ui.err("Weekly highlight", messages[result]), ephemeral=True)

    @app_commands.command(name="leaderboard", description="Rank clip submitters by approved clips, then total votes.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        if not await self._guild_only(interaction):
            return
        assert interaction.guild is not None
        rows = db.leaderboard_submitters(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(
                embed=ui.info("No clips yet", "No approved clips yet. Submit one with /clip add."),
                ephemeral=True)
            return
        lines = [f"{i}. <@{row['user_id']}> — {row['clip_count']} clip(s), ⭐ {row['total_votes']} votes"
                 for i, row in enumerate(rows, start=1)]
        await interaction.response.send_message(
            embed=ui.make("🏆 Clip leaderboard", "\n".join(lines), colour=ui.GOLD))


class Clips(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.clip = ClipGroup(bot)

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self.clip)
        if not self.weekly_loop.is_running():
            self.weekly_loop.start()

    async def cog_unload(self) -> None:
        self.weekly_loop.cancel()
        self.bot.tree.remove_command(self.clip.name)

    @tasks.loop(time=dtime(hour=9, minute=0, tzinfo=_WIB))
    async def weekly_loop(self) -> None:
        """Daily 09:00 WIB check; posts only on Mondays, once per ISO week."""
        try:
            if datetime.now(_WIB).weekday() != 0:  # Monday only
                return
            await self.bot.wait_until_ready()
            for guild in self.bot.guilds:
                try:
                    await _post_weekly(self.bot, guild)
                except Exception as e:
                    print(f"[clip] weekly highlight failed for guild {guild.id}: {e}")
        except Exception as e:
            print(f"[clip] weekly loop failed: {e}")

    @weekly_loop.before_loop
    async def _before_weekly_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Clips(bot))
