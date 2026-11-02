"""Staff gate for NEWR Clip, mirroring NEWR Social's staff.py.

A member counts as staff if ANY of these hold:
  * they are the guild owner, or
  * they hold the Administrator permission, or
  * they hold the Manage Guild permission, or
  * they hold a role whose name matches a known staff role name
    (checked by name at runtime, never by a hardcoded role ID).

The permission check alone is sufficient; the role-name check is a
fallback for servers where staff roles do not carry Manage Guild.
"""
from __future__ import annotations

import discord

import ui

_STAFF_ROLE_NAMES = frozenset({
    "founder", "executive", "admin", "administrator", "senior mod",
    "moderator", "mod", "team lead", "helper", "security", "staff",
    "support",
})


def is_staff(member: discord.Member) -> bool:
    try:
        if member.guild is not None and member.guild.owner_id == member.id:
            return True
        perms = member.guild_permissions
        if perms.administrator or perms.manage_guild:
            return True
        for role in member.roles:
            name = role.name.strip().lower()
            # Strip common emoji/prefix decoration, e.g. "⭐ Admin".
            cleaned = "".join(ch for ch in name if ch.isalnum() or ch == " ").strip()
            if cleaned in _STAFF_ROLE_NAMES or name in _STAFF_ROLE_NAMES:
                return True
    except Exception:
        return False
    return False


async def require_staff(interaction: discord.Interaction) -> bool:
    """Ephemeral staff-only denial. Returns True if the caller is staff."""
    user = interaction.user
    if isinstance(user, discord.Member) and is_staff(user):
        return True
    try:
        await interaction.response.send_message(
            embed=ui.err(
                "Staff only", "This command is staff-only."),
            ephemeral=True)
    except Exception:
        pass
    return False
