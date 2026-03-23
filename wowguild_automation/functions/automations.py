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
            wow.get("version", "retail"),
            wow.get("realm", ""),
            wow.get("guild_name", ""),
            main_char,
        )
        if not result:
            return None

        wow = guild_config.get("wow", {})
        profile_key = wow.get("version", "retail")
        rank_titles_by_profile = guild_config.get("rank_titles_by_profile", {})
        rank_titles = rank_titles_by_profile.get(profile_key) or guild_config.get("rank_titles", {})
        rank_title = rank_titles.get(str(result.rank_index), result.rank_name)

        rank_mapping_by_profile = guild_config.get("rank_mapping_by_profile", {})
        rank_mapping = rank_mapping_by_profile.get(profile_key) or guild_config.get("rank_mapping", {})
        mapped_role_id = rank_mapping.get(rank_title) or rank_mapping.get(result.rank_name)
        member_role_id = guild_config.get("roles", {}).get("member_role_id", 0)
        target_role_id = mapped_role_id or member_role_id

        if target_role_id:
            role = member.guild.get_role(int(target_role_id))
            if role and role not in member.roles:
                await member.add_roles(
                    role, reason=f"WoW guild verification succeeded ({rank_title})"
                )
        return rank_title

