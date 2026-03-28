"""Officer channel notices (rank sync, etc.) — kept separate to avoid import cycles with new_user."""

from typing import Any, Dict, Optional

import discord

from .character_helpers import game_label


async def send_protected_rank_officer_notice(
    guild: discord.Guild,
    guild_config: Dict[str, Any],
    member: discord.Member,
    profile_key: str,
    char_name: str,
    rank_title: Optional[str],
) -> None:
    """Posts to rank_protected_notify_channel_id when auto rank sync is skipped for a protected rank."""
    ch_id = int(guild_config.get("channels", {}).get("rank_protected_notify_channel_id", 0) or 0)
    if not ch_id:
        return
    channel = guild.get_channel(ch_id)
    if not isinstance(channel, discord.TextChannel):
        return
    tpl = (
        guild_config.get("templates", {}).get(
            "protected_rank_sync_notice",
            "{member} — **{game}**, Main `{char}`: Ingame-Rang **{rank}** ist geschützt; kein automatischer Discord-Rang-Sync.",
        )
        or "{member} — **{game}**, Main `{char}`: Rang **{rank}** geschützt."
    )
    gl = game_label(profile_key) if profile_key in ("retail", "mop_classic") else str(profile_key)
    try:
        text = tpl.format(
            member=member.mention,
            user=str(member),
            username=member.display_name,
            user_id=str(member.id),
            game=gl,
            char=str(char_name).strip(),
            rank=str(rank_title or "—"),
            profile=str(profile_key),
        )
        await channel.send(text[:2000])
    except discord.HTTPException:
        pass
