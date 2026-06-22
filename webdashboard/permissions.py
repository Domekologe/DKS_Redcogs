"""Mapping der Dashboard-Permission-Stufen auf Reds Rechtesystem.

Alle Zugriffe werden **serverseitig** im Gateway erzwungen. Das Frontend-Filtering
dient nur der UX.
"""
from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import discord
    from redbot.core.bot import Red

# Reihenfolge = Stärke (höher schließt niedriger ein)
LEVELS = [
    "authenticated",
    "guild_member",
    "guild_mod",
    "guild_admin",
    "guild_owner",
    "bot_owner",
]


class Level(IntEnum):
    AUTHENTICATED = 0
    GUILD_MEMBER = 1
    GUILD_MOD = 2
    GUILD_ADMIN = 3
    GUILD_OWNER = 4
    BOT_OWNER = 5


def _level_value(name: str) -> int:
    try:
        return LEVELS.index(name)
    except ValueError:
        return Level.BOT_OWNER  # unbekannt -> restriktivste Stufe


async def resolve_level(
    bot: "Red",
    user: "discord.abc.User",
    guild: "Optional[discord.Guild]" = None,
) -> int:
    """Bestimmt die höchste Stufe, die ``user`` (ggf. in ``guild``) erfüllt."""
    # Bot-Owner
    if await bot.is_owner(user):
        return Level.BOT_OWNER

    if guild is None:
        return Level.AUTHENTICATED

    member = guild.get_member(user.id)
    if member is None:
        # nicht (mehr) Mitglied dieser Guild
        return Level.AUTHENTICATED

    if guild.owner_id == member.id:
        return Level.GUILD_OWNER

    # Reds Admin/Mod-Rollen bzw. Discord-Permissions
    try:
        if await bot.is_admin(member) or member.guild_permissions.manage_guild:
            return Level.GUILD_ADMIN
    except Exception:
        if member.guild_permissions.manage_guild:
            return Level.GUILD_ADMIN
    try:
        if await bot.is_mod(member):
            return Level.GUILD_MOD
    except Exception:
        pass

    return Level.GUILD_MEMBER


async def has_permission(
    bot: "Red",
    user: "discord.abc.User",
    required: str,
    guild: "Optional[discord.Guild]" = None,
) -> bool:
    """True, wenn ``user`` mindestens die Stufe ``required`` erfüllt."""
    return await resolve_level(bot, user, guild) >= _level_value(required)
