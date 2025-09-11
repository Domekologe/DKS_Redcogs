# WoWTools/gearcheck.py
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Literal, Optional

import discord
from discord import app_commands
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n, set_contextual_locales_from_guild

_ = Translator("WoWTools", __file__)

# Welche Regionen du anbieten willst
VALID_REGIONS = ["eu", "us", "kr"]

# Blizzard Hosts
_API_HOST = {
    "eu": "eu.api.blizzard.com",
    "us": "us.api.blizzard.com",
    "kr": "kr.api.blizzard.com",
}
_AUTH_HOST = {
    "eu": "eu.battle.net",
    "us": "us.battle.net",
    "kr": "apac.battle.net",  # KR/TW auth laufen über APAC
}

def _wowhead_url(item_id: int, game: Literal["classic", "retail"]) -> str:
    if game == "classic":
        # MoP Classic Pfad
        return f"https://wowhead.com/mop-classic/item={item_id}"
    return f"https://wowhead.com/item={item_id}"

def _fmt_ilvl(item: dict) -> str:
    # Profile API: level.value (nicht immer vorhanden)
    lvl = item.get("level", {}).get("value")
    return f"ilvl {lvl}" if lvl is not None else "ilvl ?"

def _quality_emoji(quality_type: str) -> str:
    # EPIC/RARE/UNCOMMON/LEGENDARY/COMMON
    q = (quality_type or "").upper()
    return {
        "LEGENDARY": "🟧",
        "EPIC": "🟪",
        "RARE": "🟦",
        "UNCOMMON": "🟩",
        "COMMON": "⬜",
    }.get(q, "🔳")


@cog_i18n(_)
class GearCheck(commands.Cog):
    """Gearcheck über die Blizzard Profile API (Classic/Retail)."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        # kleiner OAuth-Cache pro Region
        self._lock = asyncio.Lock()
        self._tok: dict[str, str] = {}
        self._exp: dict[str, datetime] = {}

    # ---------------- OAuth ----------------

    async def _get_access_token_cached(self, region: str) -> str:
        async with self._lock:
            now = datetime.now(timezone.utc)
            tok = self._tok.get(region)
            exp = self._exp.get(region)
            if tok and exp and now < exp:
                return tok

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
            self._tok[region] = token
            self._exp[region] = now + timedelta(seconds=max(30, expires_in - 30))
            return token

    # --------------- Blizzard API ---------------

    async def _fetch_equipment(
        self,
        *,
        region: Literal["eu", "us", "kr"],
        realm: str,
        character: str,
        game: Literal["classic", "retail"] = "classic",
        locale: str = "en_US",
    ) -> dict:
        host = _API_HOST.get(region, "eu.api.blizzard.com")
        token = await self._get_access_token_cached(region)
        realm_slug = realm.lower().replace(" ", "-")
        char_slug = character.lower()

        # Namespace: profile(-classic)-{region}
        namespace = f"profile-{region}" if game == "retail" else f"profile-classic-{region}"
        url = f"https://{host}/profile/wow/character/{realm_slug}/{char_slug}/equipment"

        params = {"namespace": namespace, "locale": locale}
        headers = {"Authorization": f"Bearer {token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                js = await resp.json()
                if resp.status != 200:
                    # Liefere Rückmeldung zur Fehlersuche
                    raise RuntimeError(f"{resp.status}: {js}")
                return js

    # --------------- Command ---------------

    @commands.hybrid_command(name="gearcheck")
    @app_commands.describe(
        region="Region (eu/us/kr)",
        realm="Realm (mit Bindestrich statt Leerzeichen)",
        character="Charaktername",
        game="Classic (MoP Classic) oder Retail",
        locale="API-Lokalisierung (z.B. en_US, de_DE)",
    )
    @app_commands.choices(
        game=[
            app_commands.Choice(name="Classic", value="classic"),
            app_commands.Choice(name="Retail", value="retail"),
        ]
    )
    async def gearcheck(
        self,
        ctx: commands.Context,
        region: Literal["eu", "us", "kr"],
        realm: str,
        character: str,
        game: Literal["classic", "retail"] = "classic",
        locale: str = "en_US",
    ):
        """Zeigt das aktuell ausgerüstete Gear eines Charakters (Blizzard Profile API)."""
        if ctx.interaction:
            await set_contextual_locales_from_guild(self.bot, ctx.guild)

        region = region.lower()
        if region not in VALID_REGIONS:
            return await ctx.send(
                _("Invalid region. Valid regions are: {regions}.").format(
                    regions="`, `".join(VALID_REGIONS)
                ),
                ephemeral=True,
            )

        try:
            await ctx.defer()
        except Exception:
            pass

        try:
            data = await self._fetch_equipment(
                region=region, realm=realm, character=character, game=game, locale=locale
            )
        except Exception as e:
            ephemeral = getattr(ctx, "interaction", None) is not None
            return await ctx.send(f"Fehler beim Abrufen der Ausrüstung: {e}", ephemeral=ephemeral)

        equipped = data.get("equipped_items") or []
        if not equipped:
            return await ctx.send(_("No gear found."))

        # Ausgabe bauen (auf 2000 Zeichen achten)
        lines: List[str] = []
        hidden_count = 0

        for it in equipped:
            try:
                slot_name = it["slot"]["name"]  # z.B. Head, Neck, ...
                quality = it.get("quality", {}).get("type", "COMMON")
                emoji = _quality_emoji(quality)
                name = it.get("name", "Unknown")
                item_id = it.get("item", {}).get("id")
                ilvl_str = _fmt_ilvl(it)

                # Wowhead-Link
                link = _wowhead_url(item_id, game) if item_id else None
                head = (
                    f"**{slot_name}**: {emoji} "
                    f"[{name}]({link}) ({ilvl_str})" if link else
                    f"**{slot_name}**: {emoji} {name} ({ilvl_str})"
                )
                lines.append(head)

                # Enchants
                for ench in it.get("enchantments", []) or []:
                    d = ench.get("display_string")
                    if d:
                        lines.append(f"`└──` {d}")
            except Exception:
                # Falls Blizzard für irgendein Item ein edge-case liefert: nicht den gesamten Output killen
                continue

            # Soft-Limit, falls es zu lang wird
            if sum(len(x) + 1 for x in lines) > 1800:
                hidden_count = len(equipped) - len(lines)
                break

        if hidden_count > 0:
            lines.append(f"... und {hidden_count} weitere Einträge.")

        embed = discord.Embed(
            title=f"{character.title()} – {realm.title()} ({region.upper()}) [{game.capitalize()}]",
            description="\n".join(lines),
            color=await ctx.embed_color(),
        )

        # Zeitpunkt? (nicht immer verfügbar bei Profile API)
        # Wenn du 'last_login_timestamp' o.ä. irgendwann verwenden willst, könntest du hier Footer setzen.

        ephemeral = getattr(ctx, "interaction", None) is not None
        await ctx.send(embed=embed, ephemeral=ephemeral)

    # --------- Autocomplete ---------
    @gearcheck.autocomplete("region")
    async def ac_region(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        current = (current or "").lower()
        return [
            app_commands.Choice(name=r.upper(), value=r)
            for r in VALID_REGIONS
            if current in r
        ][:25]
