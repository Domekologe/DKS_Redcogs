from typing import Optional

import discord

from .blizzard import BlizzardService


class RankSyncService:
    def __init__(self, blizzard: BlizzardService) -> None:
        self.blizzard = blizzard

    async def sync_member_rank(
        self,
        member: discord.Member,
        guild_config: dict,
        main_char: str,
    ) -> Optional[str]:
        wow = guild_config.get("wow", {})
        result = await self.blizzard.search_member(
            wow.get("region", ""),
            wow.get("realm", ""),
            wow.get("guild_name", ""),
            main_char,
        )
        if not result:
            return None

        # Base implementation: apply configured member role when verified.
        member_role_id = guild_config.get("roles", {}).get("member_role_id", 0)
        if member_role_id:
            role = member.guild.get_role(member_role_id)
            if role and role not in member.roles:
                await member.add_roles(role, reason="WoW guild verification succeeded")
        return result.rank_name

