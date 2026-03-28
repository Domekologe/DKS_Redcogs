from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Set, Tuple

import discord

from .blizzard import BlizzardService


@dataclass(frozen=True)
class RankSyncPlan:
    """Ergebnis der API-/Mapping-Auswertung (ohne Rollenänderung)."""

    rank_title: Optional[str]
    target_role_id: int
    mapped_role_ids: FrozenSet[int]
    protected_skip: bool = False


class RankSyncService:
    def __init__(self, blizzard: BlizzardService) -> None:
        self.blizzard = blizzard

    def mapped_role_ids_for_profile(self, guild_config: dict, profile_key: str) -> Set[int]:
        rank_mapping_by_profile = guild_config.get("rank_mapping_by_profile", {})
        m = rank_mapping_by_profile.get(profile_key) or guild_config.get("rank_mapping", {})
        out: Set[int] = set()
        for v in m.values():
            try:
                out.add(int(v))
            except (TypeError, ValueError):
                continue
        return out

    def is_rank_protected(
        self,
        guild_config: dict,
        profile_key: str,
        rank_title: Optional[str],
        rank_index: int,
        api_rank_name: str,
    ) -> bool:
        raw = guild_config.get("protected_rank_titles_by_profile") or {}
        entries = raw.get(profile_key)
        if not entries:
            return False
        if isinstance(entries, str):
            entries = [entries]
        if not isinstance(entries, (list, tuple, set)):
            return False
        normalized = {str(e).strip().lower() for e in entries if str(e).strip()}
        if not normalized:
            return False
        candidates: List[str] = []
        if rank_title:
            rt = str(rank_title).strip().lower()
            candidates.append(rt)
            if rt.startswith("rank "):
                candidates.append(rt.replace("rank ", "", 1).strip())
        if api_rank_name:
            an = str(api_rank_name).strip().lower()
            candidates.append(an)
            if an.startswith("rank "):
                candidates.append(an.replace("rank ", "", 1).strip())
        candidates.append(str(int(rank_index)))
        candidates.append(f"rank {int(rank_index)}")
        return any(c and c in normalized for c in candidates)

    async def plan_sync(
        self,
        guild_config: dict,
        main_char: str,
        profile_key: str,
    ) -> RankSyncPlan:
        wow_profiles = guild_config.get("wow_profiles") or {}
        wow = wow_profiles.get(profile_key) or guild_config.get("wow", {})
        if not wow:
            return RankSyncPlan(None, 0, frozenset(), False)

        region = wow.get("region", "")
        version = wow.get("version", profile_key)
        realm = wow.get("realm", "")
        guild_name = wow.get("guild_name", "")
        result = await self.blizzard.search_member(region, version, realm, guild_name, main_char)
        mapped = self.mapped_role_ids_for_profile(guild_config, profile_key)

        if not result:
            return RankSyncPlan(None, 0, frozenset(mapped), False)

        rank_titles_by_profile = guild_config.get("rank_titles_by_profile", {})
        rank_titles = rank_titles_by_profile.get(profile_key) or guild_config.get("rank_titles", {})
        rank_title = rank_titles.get(str(result.rank_index), result.rank_name)

        if self.is_rank_protected(
            guild_config,
            profile_key,
            rank_title,
            int(result.rank_index),
            str(result.rank_name or ""),
        ):
            return RankSyncPlan(
                rank_title=rank_title,
                target_role_id=0,
                mapped_role_ids=frozenset(mapped),
                protected_skip=True,
            )

        rank_mapping_by_profile = guild_config.get("rank_mapping_by_profile", {})
        rank_mapping = rank_mapping_by_profile.get(profile_key) or guild_config.get("rank_mapping", {})
        mapped_role_id = rank_mapping.get(rank_title) or rank_mapping.get(result.rank_name)
        member_role_id = guild_config.get("roles", {}).get("member_role_id", 0)
        target_role_id = int(mapped_role_id or member_role_id or 0)

        return RankSyncPlan(
            rank_title=rank_title,
            target_role_id=target_role_id,
            mapped_role_ids=frozenset(mapped),
            protected_skip=False,
        )

    async def apply_plan(
        self,
        member: discord.Member,
        plan: RankSyncPlan,
        *,
        locked: bool,
    ) -> Tuple[bool, str]:
        """
        Wendet den Plan an. Wenn locked: keine Rollenänderung.
        Returns (applied_successfully, reason) reason in {ok, locked, not_found, no_role, no_perms}
        """
        if locked:
            return False, "locked"
        if not plan.rank_title:
            return False, "not_found"
        if not plan.target_role_id:
            return False, "no_role"

        target = member.guild.get_role(int(plan.target_role_id))
        if not target:
            return False, "no_role"

        to_remove: List[discord.Role] = []
        mapped_ids = set(plan.mapped_role_ids)
        for r in member.roles:
            if r.id in mapped_ids and r.id != plan.target_role_id:
                to_remove.append(r)

        try:
            if to_remove:
                await member.remove_roles(
                    *to_remove,
                    reason="WoW-Rang-Sync: alte Gildenrang-Rolle(n) ersetzen",
                )
            if target not in member.roles:
                await member.add_roles(
                    target,
                    reason=f"WoW-Rang-Sync: {plan.rank_title}",
                )
        except discord.Forbidden:
            return False, "no_perms"
        except discord.HTTPException:
            return False, "http"

        return True, "ok"

    async def sync_member_rank(
        self,
        member: discord.Member,
        guild_config: dict,
        main_char: str,
        *,
        profile_key: str,
        locked: bool,
    ) -> Tuple[Optional[str], str, int]:
        """
        Plan + Apply in einem Schritt.
        Returns (rank_title_or_none, reason, applied_role_id bei Erfolg sonst 0).
        """
        plan = await self.plan_sync(guild_config, main_char, profile_key)
        if locked:
            return plan.rank_title, "locked", 0
        if plan.protected_skip:
            return plan.rank_title, "protected", 0
        ok, reason = await self.apply_plan(member, plan, locked=False)
        if not ok:
            return plan.rank_title, reason, 0
        return plan.rank_title, "ok", int(plan.target_role_id)
