from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class GuildMember:
    character_name: str
    rank_name: str


class BlizzardService:
    """
    Placeholder service.
    Replace stubs with OAuth + official Blizzard API calls.
    """

    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret

    async def search_member(
        self, region: str, realm: str, guild_name: str, character_name: str
    ) -> Optional[GuildMember]:
        if not (region and realm and guild_name and character_name):
            return None
        # Mock behavior for first usable implementation:
        # if character name has at least 3 chars, we mark it as found.
        if len(character_name.strip()) >= 3:
            return GuildMember(character_name=character_name.strip(), rank_name="Raider")
        return None

    async def get_member_characters(
        self, region: str, realm: str, guild_name: str, character_name: str
    ) -> List[Dict[str, str]]:
        member = await self.search_member(region, realm, guild_name, character_name)
        if not member:
            return []
        return [{"name": member.character_name, "realm": realm, "rank": member.rank_name}]

