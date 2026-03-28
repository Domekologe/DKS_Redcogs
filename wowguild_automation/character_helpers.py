"""Linked WoW characters per member: Retail + MoP Classic, guild roster validation, uniqueness."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

import discord
from redbot.core import Config

GAME_RETAIL = "retail"
GAME_MOP = "mop_classic"
SUPPORTED_GAMES = (GAME_RETAIL, GAME_MOP)
GAME_LABELS = {GAME_RETAIL: "Retail", GAME_MOP: "MoP Classic"}


def game_label(game_type: str) -> str:
    return GAME_LABELS.get(game_type, game_type)


def char_tuple_key(name: str, game_type: str) -> Tuple[str, str]:
    return (name.strip().lower(), (game_type or GAME_RETAIL).lower())


def normalize_linked_characters(raw: Any) -> List[Dict[str, str]]:
    """Migrate legacy list[str] to [{name, game_type}]."""
    if not raw:
        return []
    out: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                n = item.strip()
                if not n:
                    continue
                key = char_tuple_key(n, GAME_RETAIL)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"name": n, "game_type": GAME_RETAIL})
            elif isinstance(item, dict):
                n = str(item.get("name", "")).strip()
                g = str(item.get("game_type", GAME_RETAIL)).lower()
                if g not in SUPPORTED_GAMES:
                    g = GAME_RETAIL
                if not n:
                    continue
                key = char_tuple_key(n, g)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"name": n, "game_type": g})
    return out


async def get_linked_list(member_group: Config) -> List[Dict[str, str]]:
    linked = await member_group.linked_characters()
    if linked:
        return normalize_linked_characters(linked)
    legacy = await member_group.chars()
    return normalize_linked_characters(legacy)


async def set_linked_list(member_group: Config, items: List[Dict[str, str]]) -> None:
    clean: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for it in items:
        n = str(it.get("name", "")).strip()
        g = str(it.get("game_type", GAME_RETAIL)).lower()
        if g not in SUPPORTED_GAMES or not n:
            continue
        key = char_tuple_key(n, g)
        if key in seen:
            continue
        seen.add(key)
        clean.append({"name": n, "game_type": g})
    await member_group.linked_characters.set(clean)
    await member_group.chars.set([f"{x['name']} ({x['game_type']})" for x in clean])


def format_char_line(entry: Dict[str, str], main: Optional[Dict[str, str]] = None) -> str:
    tag = f"{entry['name']} ({game_label(entry['game_type'])})"
    if main and main.get("name") and main.get("game_type"):
        if (
            main["name"].lower() == entry["name"].lower()
            and main["game_type"].lower() == entry["game_type"].lower()
        ):
            return f"**{tag}** (Main)"
    return tag


async def find_char_owner_guild_wide(
    config: Config,
    guild: discord.Guild,
    name: str,
    game_type: str,
    exclude_user_id: Optional[int] = None,
) -> Optional[int]:
    key = char_tuple_key(name, game_type)
    data = await config.all_members(guild)
    for uid_str, payload in data.items():
        try:
            uid = int(uid_str)
        except (TypeError, ValueError):
            continue
        if exclude_user_id is not None and uid == exclude_user_id:
            continue
        linked = normalize_linked_characters(payload.get("linked_characters") or payload.get("chars"))
        for e in linked:
            if char_tuple_key(e["name"], e["game_type"]) == key:
                return uid
    return None


async def wow_profile_for_game(guild_config: Dict[str, Any], game_type: str) -> Optional[Dict[str, Any]]:
    profiles = guild_config.get("wow_profiles") or {}
    if game_type in profiles:
        return profiles[game_type]
    single = guild_config.get("wow") or {}
    if single.get("version") == game_type:
        return single
    return None
