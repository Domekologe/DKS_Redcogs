import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List

import discord
from discord import app_commands
from redbot.core import commands
from redbot.core.i18n import Translator, set_contextual_locales_from_guild

from .utils import format_to_gold

_ = Translator("WoWTools", __file__)

VALID_REGIONS = ["eu", "us", "kr"]

# Mapping für API- und Auth-Hosts
_API_HOST = {
    "eu": "eu.api.blizzard.com",
    "us": "us.api.blizzard.com",
    "kr": "kr.api.blizzard.com",
}
_AUTH_HOST = {
    "eu": "eu.battle.net",
    "us": "us.battle.net",
    "kr": "apac.battle.net",  # KR/TW laufen über APAC-Auth
}


async def _get_access_token_cached(self, region: str) -> str:
    """Holt oder cached den Access Token für die Blizzard API"""
    if not hasattr(self, "_wowtoken_lock"):
        self._wowtoken_lock = asyncio.Lock()
    if not hasattr(self, "_wowtoken_tok"):
        self._wowtoken_tok = {}
    if not hasattr(self, "_wowtoken_exp"):
        self._wowtoken_exp = {}

    async with self._wowtoken_lock:
        now = datetime.now(timezone.utc)
        tok = self._wowtoken_tok.get(region)
        exp = self._wowtoken_exp.get(region)
        if tok and exp and now < exp:
            return tok

        # API Keys aus Red holen
        api_tokens = await self.bot.get_shared_api_tokens("blizzard")
        cid, secret = api_tokens.get("client_id"), api_tokens.get("client_secret")
        if not cid or not secret:
            raise RuntimeError(
                "Blizzard API nicht eingerichtet. Nutze: "
                "`[p]set api blizzard client_id,<id> client_secret,<secret>`"
            )

        auth_host = _AUTH_HOST.get(region, "eu.battle.net")
        url = f"https://{auth_host}/oauth/token"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data={"grant_type": "client_credentials"},
                auth=aiohttp.BasicAuth(cid, secret),
            ) as resp:
                js = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"Auth {resp.status}: {js}")
        token = js["access_token"]
        expires_in = int(js.get("expires_in", 3600))
        # 30 Sekunden Puffer
        self._wowtoken_tok[region] = token
        self._wowtoken_exp[region] = now + timedelta(seconds=expires_in - 30)
        return token


async def _fetch_token_price(self, region: str, game: str = "classic", locale: str = "en_US") -> dict:
    """Fragt den Tokenpreis von der Blizzard-API ab"""
    host = _API_HOST.get(region, "eu.api.blizzard.com")
    namespace = f"dynamic-{region}" if game == "retail" else f"dynamic-classic-{region}"
    url = f"https://{host}/data/wow/token/index"
    token = await _get_access_token_cached(self, region)

    params = {"namespace": namespace, "locale": locale}
    headers = {"Authorization": f"Bearer {token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            js = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"API {resp.status}: {js}")
            return js


class Token:
    @commands.hybrid_command()
    async def wowtoken(self, ctx: commands.Context, region: str = "all"):
        """Check price of WoW token in a region"""
        if ctx.interaction:
            # Workaround für Red-Locale bei Interactions
            await set_contextual_locales_from_guild(self.bot, ctx.guild)

        region = region.lower()
        await ctx.defer()

        try:
            if region == "all":
                await self.priceall(ctx)
                return

            if region not in VALID_REGIONS:
                await ctx.send(
                    _("Invalid region. Valid regions are: `eu`, `us`, `kr` or `all`."),
                    ephemeral=True,
                )
                return

            # Classic als Standard (wie vorher in deiner Datei)
            data = await _fetch_token_price(self, region=region, game="classic", locale="en_US")
            price_copper = int(data.get("price", 0))

            gold_emotes = await self.config.emotes()
            message = _("Current price of the {region} WoW Token is: **{gold}**").format(
                region=region.upper(), gold=format_to_gold(price_copper, gold_emotes)
            )

            if ctx.channel.permissions_for(ctx.guild.me).embed_links:
                embed = discord.Embed(description=message, colour=await ctx.embed_colour())
                ts = data.get("last_updated_timestamp")
                if ts:
                    dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
                    embed.set_footer(text=f"Last update: {dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                await ctx.send(embed=embed)
            else:
                await ctx.send(message)

        except Exception as e:
            ephemeral = getattr(ctx, "interaction", None) is not None
            await ctx.send(_("Command failed successfully. {e}").format(e=e), ephemeral=ephemeral)

    @wowtoken.autocomplete("region")
    async def wowtoken_region_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=region, value=region)
            for region in ["All"] + VALID_REGIONS
            if current.lower() in region.lower()
        ]

    async def priceall(self, ctx: commands.Context):
        """Check price of the WoW token in all supported regions"""
        try:
            await ctx.defer()
        except Exception:
            pass

        embed = discord.Embed(title=_("WoW Token prices"), colour=await ctx.embed_colour())
        for region in VALID_REGIONS:
            try:
                data = await _fetch_token_price(self, region=region, game="classic", locale="en_US")
                price_copper = int(data.get("price", 0))
                gold_emotes = await self.config.emotes()
                embed.add_field(
                    name=region.upper(),
                    value=format_to_gold(price_copper, gold_emotes),
                )
            except Exception as e:
                embed.add_field(name=region.upper(), value=f"Error: {e}")

        if ctx.channel.permissions_for(ctx.guild.me).embed_links:
            await ctx.send(embed=embed)
        else:
            msg = _("Current prices of the WoW Token in all regions:\n")
            for field in embed.fields:
                msg += f"{field.name}: {field.value}\n"
            await ctx.send(msg)
