import aiohttp
import time
import asyncio
from typing import Optional, Dict, Any


class BlizzardAPIError(Exception):
    pass


class BlizzardAPI:
    """
    Blizzard API wrapper with:
    - OAuth token caching
    - Character data caching (TTL)
    - Retry & exponential backoff
    - 429 handling (Retry-After)
    """

    # -------------------------------
    # CONFIG
    # -------------------------------
    CACHE_TTL_SECONDS = 60 * 60        # 1 hour
    MAX_RETRIES = 3
    BACKOFF_BASE = 2                  # exponential backoff

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        region: str = "eu",
        locale: str = "en_US"
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.region = region.lower()
        self.locale = locale

        self.base_url = f"https://{self.region}.api.blizzard.com"
        self.oauth_url = f"https://{self.region}.battle.net/oauth/token"

        self._token: Optional[str] = None
        self._token_expires: int = 0

        # Simple in-memory cache
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ==================================================
    # AUTH
    # ==================================================

    async def _get_token(self) -> str:
        now = int(time.time())

        if self._token and now < self._token_expires:
            return self._token

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.oauth_url,
                data={"grant_type": "client_credentials"},
                auth=aiohttp.BasicAuth(self.client_id, self.client_secret)
            ) as resp:
                if resp.status != 200:
                    raise BlizzardAPIError(
                        f"OAuth failed (status {resp.status})"
                    )
                data = await resp.json()

        self._token = data["access_token"]
        self._token_expires = now + data["expires_in"] - 60
        return self._token

    # ==================================================
    # INTERNAL REQUEST WITH RETRY
    # ==================================================

    async def _get(
        self,
        endpoint: str,
        namespace: str,
        cache_key: Optional[str] = None
    ) -> dict:
        now = int(time.time())

        # -------------------------------
        # CACHE CHECK
        # -------------------------------
        if cache_key:
            cached = self._cache.get(cache_key)
            if cached and now - cached["cached_at"] < self.CACHE_TTL_SECONDS:
                return cached["data"]

        token = await self._get_token()

        headers = {
            "Authorization": f"Bearer {token}"
        }

        params = {
            "namespace": namespace,
            "locale": self.locale
        }

        attempt = 0
        while attempt < self.MAX_RETRIES:
            attempt += 1

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}{endpoint}",
                    headers=headers,
                    params=params
                ) as resp:

                    # -------------------------------
                    # SUCCESS
                    # -------------------------------
                    if resp.status == 200:
                        data = await resp.json()

                        if cache_key:
                            self._cache[cache_key] = {
                                "data": data,
                                "cached_at": now
                            }

                        return data

                    # -------------------------------
                    # NOT FOUND (valid result)
                    # -------------------------------
                    if resp.status == 404:
                        return {}

                    # -------------------------------
                    # RATE LIMIT
                    # -------------------------------
                    if resp.status == 429:
                        retry_after = int(
                            resp.headers.get("Retry-After", "1")
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    # -------------------------------
                    # OTHER ERRORS
                    # -------------------------------
                    if attempt >= self.MAX_RETRIES:
                        raise BlizzardAPIError(
                            f"API error {resp.status} on {endpoint}"
                        )

                    await asyncio.sleep(self.BACKOFF_BASE ** attempt)

        return {}

    # ==================================================
    # NAMESPACE
    # ==================================================

    def _profile_namespace(self, game_version: str) -> str:
        if game_version == "retail":
            return f"profile-{self.region}"

        # Classic Era + MoP Classic
        return f"profile-classic-{self.region}"

    # ==================================================
    # CHARACTER
    # ==================================================

    async def get_character(
        self,
        name: str,
        realm: str,
        game_version: str
    ) -> dict:
        name = name.lower()
        realm = realm.lower()

        cache_key = f"{name}-{realm}-{game_version}"

        endpoint = (
            f"/profile/wow/character/"
            f"{realm}/{name}"
        )

        return await self._get(
            endpoint,
            self._profile_namespace(game_version),
            cache_key=cache_key
        )

    async def character_exists(
        self,
        name: str,
        realm: str,
        game_version: str
    ) -> bool:
        return bool(
            await self.get_character(name, realm, game_version)
        )

    # ==================================================
    # GUILD
    # ==================================================

    async def is_character_in_guild(
        self,
        name: str,
        realm: str,
        expected_guild: str,
        game_version: str
    ) -> bool:
        data = await self.get_character(
            name,
            realm,
            game_version
        )

        if not data:
            return False

        guild = data.get("guild")
        if not guild:
            return False

        return guild.get("name", "").lower() == expected_guild.lower()

    async def get_character_guild_rank(
        self,
        name: str,
        realm: str,
        game_version: str
    ) -> Optional[int]:
        data = await self.get_character(
            name,
            realm,
            game_version
        )

        guild = data.get("guild")
        if not guild:
            return None

        return guild.get("rank")

    # ==================================================
    # CACHE UTILITIES
    # ==================================================

    def clear_cache(self):
        """Manual cache clear (admin/debug)"""
        self._cache.clear()

    def cache_stats(self) -> dict:
        return {
            "entries": len(self._cache),
            "ttl_seconds": self.CACHE_TTL_SECONDS
        }
