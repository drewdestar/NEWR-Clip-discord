"""Shared premium embed helpers for NEWR Clip.

Design system (same palette as the other new bots):
  * Palette: blurple 0x5865F2 (primary/info), success 0x57F287,
    error 0xED4245, warning 0xFEE75C, gold 0xF5C518 (leaderboard
    and top clips only).
  * Every embed gets footer "NEWR Clip • NEWR LABS" plus a
    timestamp via discord.utils.utcnow().
  * Titles use a single leading emoji. The ok/err/warn/info
    wrappers add their own leading emoji, so pass them a plain
    title; panel/make take the full title (including its emoji)
    as given.
"""
from __future__ import annotations

import discord

BLURPLE = 0x5865F2
PRIMARY = BLURPLE
SUCCESS = 0x57F287
ERROR = 0xED4245
WARNING = 0xFEE75C
GOLD = 0xF5C518

FOOTER = "NEWR Clip • NEWR LABS"


def panel(title: str, description: str | None = None,
          colour: int = BLURPLE) -> discord.Embed:
    """Base embed: title, description, colour, bot footer, timestamp."""
    embed = discord.Embed(
        title=title,
        description=description,
        colour=colour,
        timestamp=discord.utils.utcnow())
    embed.set_footer(text=FOOTER)
    return embed


def make(title: str, description: str | None = None, colour: int = BLURPLE,
         fields: list | None = None,
         thumbnail: str | None = None,
         image: str | None = None) -> discord.Embed:
    """Embed with optional fields, thumbnail, and image.

    Each field is a (name, value) or (name, value, inline) tuple,
    or a dict with name/value/inline keys.
    """
    embed = panel(title, description, colour)
    for field in fields or []:
        if isinstance(field, dict):
            embed.add_field(name=field["name"], value=field["value"],
                            inline=field.get("inline", False))
        elif len(field) == 3:
            name, value, inline = field
            embed.add_field(name=name, value=value, inline=inline)
        else:
            name, value = field
            embed.add_field(name=name, value=value, inline=False)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    return embed


def ok(title: str, description: str | None = None) -> discord.Embed:
    """Success embed (green). Pass a plain title; ✅ is added."""
    return panel(f"✅ {title}", description, SUCCESS)


def err(title: str, description: str | None = None) -> discord.Embed:
    """Error embed (red). Pass a plain title; ❌ is added."""
    return panel(f"❌ {title}", description, ERROR)


def warn(title: str, description: str | None = None) -> discord.Embed:
    """Warning embed (yellow). Pass a plain title; ⚠️ is added."""
    return panel(f"⚠️ {title}", description, WARNING)


def info(title: str, description: str | None = None) -> discord.Embed:
    """Info embed (blurple). Pass a plain title; ℹ️ is added."""
    return panel(f"ℹ️ {title}", description, BLURPLE)
