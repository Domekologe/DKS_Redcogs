# token.py
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal

import discord
from discord import app_commands
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n, set_contextual_locales_from_guild

_ = Translator("WoWToolsToken", __file__)

REGION_HOSTS = {
    "eu": "eu.api.blizzard.com",
    "us": "us.api.blizzard.com",
    # Wenn du später KR/TW/SEA brauchst, ergänzen:
    # "kr": "kr.api.blizzard.com",
    # "tw": "tw.api.blizzard.com",
}

BATTLE_NET_AUTH = {
    "eu": "eu.battle.net",
    "us": "us.battle.net",
    # "kr": "apac.battle.net",
    # "tw": "apac.battle.net",
}

@cog_i18n(_)
class Token(commands.Cog):
    """Zeigt WoW-Tokenpreise (Retail oder Classic) aus der offiziellen Blizzard-API."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._lock = asyncio.Lock()

    # --------------- Utilities ---------------

    async def _get_api_keys(self) -> tuple[str, str]:
        tokens = await self.bot.get_shared_api_tokens("blizzard")
        client_id = tokens.get("client_id")
        client_secret = tokens.get("client_secret")
        if not client_id or not client_secret:
            raise RuntimeError(
                "Blizzard API Keys fehlen. Setze sie mit: "
                "`[p]set api blizzard client_id,<id> client_secret,<secret>`"
            )
        return client_id, client_secret

    async def _fetch_access_token(self, region: str) -> tuple[str, int]:
        client_id, client_secret = await self._get_api_keys()
        auth_host = BATTLE_NET_AUTH.get(region, BATTLE_NET_AUTH["eu"])
        url = f"https://{auth_host}/oauth/token"

        async with aiohttp.ClientSession() as session:
            data = {"grant_type": "client_credentials"}
            auth = aiohttp.BasicAuth(client_id, client_secret)
            async with session.post(url, data=data, auth=auth) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Token-Request fehlgeschlagen ({resp.status}): {text}")
                js = await resp.json()
                return js["access_token"], int(js.get("expires_in", 3600))

    async def _get_access_token_cached(self, region: str) -> str:
        async with self._lock:
            now = datetime.now(timezone.utc)
            if self._access_token and self._token_expires_at and now < self._token_expires_at:
                return self._access_token

            token, expires_in = await self._fetch_access_token(region)
            # 30 Sekunden Puffer
            self._access_token = token
            self._token_expires_at = now + timedelta(seconds=expires_in - 30)
            return token

    async def _get_token_price(
        self,
        region: Literal["eu", "us"],
        game: Literal["retail", "classic"],
        locale: str = "en_US",
    ) -> dict:
        """
        Ruft Tokenpreis aus der offiziellen Blizzard-API ab.
        - Retail:  namespace = dynamic-{region}
        - Classic: namespace = dynamic-classic-{region}
        """
        host = REGION_HOSTS.get(region, REGION_HOSTS["eu"])
        namespace = f"dynamic-{region}" if game == "retail" else f"dynamic-classic-{region}"
        url = f"https://{host}/data/wow/token/index"
        token = await self._get_access_token_cached(region)

        params = {"namespace": namespace, "locale": locale}
        headers = {"Authorization": f"Bearer {token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                js = await resp.json()
                if resp.status != 200:
                    # Liefere sinnvolle Fehlermeldung zurück
                    raise RuntimeError(f"API-Fehler {resp.status}: {js}")
                return js

    @staticmethod
    def _format_gold(price_copper: int) -> str:
        # Blizzard liefert den Preis in Kupfer
        gold = price_copper // 10000
        silver = (price_copper // 100) % 100
        copper = price_copper % 100
        # Deutsch üblich: Punkt als Tausendertrenner
        return f"{gold:,}".replace(",", ".") + f"g {silver:02d}s {copper:02d}c"

    @staticmethod
    def _ts_ms_to_dt_utc(ts_ms: int) -> datetime:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

    # --------------- Command ---------------

    @commands.hybrid_command(name="wowtoken", aliases=["token"])
    @app_commands.describe(
        game="Retail oder Classic",
        region="Region (EU/US)",
        locale="API-Lokalisierung (z.B. en_US, de_DE)",
    )
    @app_commands.choices(
        game=[
            app_commands.Choice(name="Retail", value="retail"),
            app_commands.Choice(name="Classic", value="classic"),
        ],
        region=[
            app_commands.Choice(name="EU", value="eu"),
            app_commands.Choice(name="US", value="us"),
        ],
    )
    async def wowtoken_cmd(
        self,
        ctx: commands.Context,
        game: Literal["retail", "classic"] = "retail",
        region: Literal["eu", "us"] = "eu",
        locale: str = "en_US",
    ):
        """
        Zeigt den aktuellen WoW-Tokenpreis (offizielle Blizzard-API).
        Beispiel: /wowtoken game:classic region:eu
        """
        # Locale-Fix für Interactions (Red-Bug-Workaround)
        if ctx.interaction:
            await set_contextual_locales_from_guild(self.bot, ctx.guild)

        try:
            await ctx.defer()
        except Exception:
            pass

        try:
            data = await self._get_token_price(region=region, game=game, locale=locale)
        except Exception as e:
            ephemeral = getattr(ctx, "interaction", None) is not None
            return await ctx.send(f"Fehler beim Abrufen des Tokenpreises: {e}", ephemeral=ephemeral)

        price_copper = int(data.get("price", 0))
        last_updated_ms = int(data.get("last_updated_timestamp", 0))
        last_dt = self._ts_ms_to_dt_utc(last_updated_ms) if last_updated_ms else None

        price_text = self._format_gold(price_copper)
        title = f"WoW Token – {game.capitalize()} – {region.upper()}"

        embed = discord.Embed(title=title, color=await ctx.embed_color())
        embed.add_field(name=_("Preis"), value=price_text, inline=True)
        embed.add_field(name=_("Rohwert (Kupfer)"), value=f"{price_copper:,}".replace(",", "."), inline=True)
        if last_dt:
            # Zeige sowohl UTC als auch relative Zeit
            embed.set_footer(text=f"Last update: {last_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        ephemeral = getattr(ctx, "interaction", None) is not None
        await ctx.send(embed=embed, ephemeral=ephemeral)


async def setup(bot: Red):
    await bot.add_cog(WoWToken(bot))
