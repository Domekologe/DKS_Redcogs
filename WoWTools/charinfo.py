# WoWTools/charinfo.py
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Literal, Dict, Optional

import discord
from discord import app_commands
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n, set_contextual_locales_from_guild

from .autocomplete import (
    REGIONS as AC_REGIONS,
    REALMS as AC_REALMS,
    _LANG_CODES as AC_LANG_CODES,
    _API_HOST,
    _AUTH_HOST,
)

_ = Translator("WoWTools", __file__)

def _resolve_locale(lang_or_locale: str) -> str:
    if not lang_or_locale:
        return "en_US"
    key = lang_or_locale.lower()
    return AC_LANG_CODES.get(key, lang_or_locale)

def _pct(v: Optional[float]) -> str:
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return "?"

def _fmt_rating_block(node: Optional[dict]) -> str:
    if not node:
        return "?"
    val = node.get("value")
    rn = node.get("rating_normalized")
    if val is None and rn is None:
        return "?"
    if val is None:
        return f"(RN {rn})"
    if rn is None:
        return _pct(val)
    return f"{_pct(val)} (RN {rn})"

# OAuth Cache
def _ensure_oauth_state(self):
    if not hasattr(self, "_tok_lock"):
        self._tok_lock = asyncio.Lock()
    if not hasattr(self, "_tok"):
        self._tok: Dict[str, str] = {}
    if not hasattr(self, "_exp"):
        self._exp: Dict[str, datetime] = {}

async def _get_access_token(self, region: str) -> str:
    _ensure_oauth_state(self)
    async with self._tok_lock:
        now = datetime.now(timezone.utc)
        if self._tok.get(region) and self._exp.get(region) and now < self._exp[region]:
            return self._tok[region]
        api_tokens = await self.bot.get_shared_api_tokens("blizzard")
        cid, secret = api_tokens.get("client_id"), api_tokens.get("client_secret")
        if not cid or not secret:
            raise RuntimeError("Blizzard API nicht eingerichtet. `[p]set api blizzard client_id,<id> client_secret,<secret>`")
        auth_host = _AUTH_HOST.get(region, "eu.battle.net")
        url = f"https://{auth_host}/oauth/token"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data={"grant_type": "client_credentials"}, auth=aiohttp.BasicAuth(cid, secret)) as resp:
                js = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"Auth {resp.status}: {js}")
        token = js["access_token"]
        expires_in = int(js.get("expires_in", 3600))
        self._tok[region] = token
        self._exp[region] = now + timedelta(seconds=max(30, expires_in - 30))
        return token

async def _fetch_statistics(
    self,
    *,
    region: Literal["eu", "us", "kr", "tw"],
    realm: str,
    character: str,
    game: Literal["classic", "retail"] = "classic",
    locale: str = "en_US",
) -> dict:
    host = _API_HOST.get(region, "eu.api.blizzard.com")
    token = await _get_access_token(self, region)
    namespace = f"profile-{region}" if game == "retail" else f"profile-classic-{region}"
    url = f"https://{host}/profile/wow/character/{realm}/{character}/statistics"
    params = {"namespace": namespace, "locale": locale}
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, headers=headers) as resp:
            js = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"{resp.status}: {js}")
            return js

@cog_i18n(_)
class CharInfo(commands.Cog):
    """Zeigt Kern-Charakterwerte (HP, Mana, Primärwerte, Crit/Haste/Mastery, etc.)."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot

    @commands.hybrid_command(name="charinfo")
    @app_commands.describe(
        region="Region (eu/us/kr/tw)",
        realm="Realm (mit Bindestrich statt Leerzeichen)",
        character="Charaktername",
        game="Classic (MoP Classic) oder Retail",
        locale="Locale (z. B. de oder de_DE, en oder en_US)",
    )
    @app_commands.choices(
        game=[
            app_commands.Choice(name="Classic", value="classic"),
            app_commands.Choice(name="Retail", value="retail"),
        ]
    )
    async def charinfo(
        self,
        ctx: commands.Context,
        region: Literal["eu", "us", "kr", "tw"],
        realm: str,
        character: str,
        game: Literal["classic", "retail"] = "classic",
        locale: str = "en",
    ):
        if ctx.interaction:
            await set_contextual_locales_from_guild(self.bot, ctx.guild)
        region = region.lower()
        locale = _resolve_locale(locale)
        realm_slug = realm.lower().replace(" ", "-")
        char_slug = character.lower()

        try:
            await ctx.defer()
        except Exception:
            pass

        try:
            js = await _fetch_statistics(self, region=region, realm=realm_slug, character=char_slug, game=game, locale=locale)
        except Exception as e:
            return await ctx.send(f"Fehler beim Abrufen der Charakterwerte: {e}", ephemeral=bool(ctx.interaction))

        # Rohwerte
        health = js.get("health")
        power = js.get("power")
        power_type = (js.get("power_type") or {}).get("name")

        strength = (js.get("strength") or {}).get("effective")
        agility  = (js.get("agility") or {}).get("effective")
        intellect = (js.get("intellect") or {}).get("effective")
        stamina  = (js.get("stamina") or {}).get("effective")

        armor_eff = (js.get("armor") or {}).get("effective")
        spell_power = js.get("spell_power")

        melee_crit = _fmt_rating_block(js.get("melee_crit"))
        melee_haste = _fmt_rating_block(js.get("melee_haste"))
        spell_crit = _fmt_rating_block(js.get("spell_crit"))
        spell_haste = _fmt_rating_block(js.get("spell_haste"))
        ranged_crit = _fmt_rating_block(js.get("ranged_crit"))
        ranged_haste = _fmt_rating_block(js.get("ranged_haste"))
        mastery = _fmt_rating_block(js.get("mastery"))

        mana_regen = js.get("mana_regen")
        mana_regen_combat = js.get("mana_regen_combat")

        lines = []
        lines.append(f"**Health:** {health:,}" if isinstance(health, int) else f"**Health:** {health}")
        if power_type:
            lines.append(f"**{power_type}:** {power:,}" if isinstance(power, int) else f"**{power_type}:** {power}")

        lines.append("")
        lines.append(f"**Strength:** {strength}")
        lines.append(f"**Agility:** {agility}")
        lines.append(f"**Intellect:** {intellect}")
        lines.append(f"**Stamina:** {stamina}")

        lines.append("")
        lines.append(f"**Armor:** {armor_eff}")
        lines.append(f"**Spell Power:** {spell_power}")

        lines.append("")
        lines.append(f"**Melee Crit:** {melee_crit}")
        lines.append(f"**Melee Haste:** {melee_haste}")
        lines.append(f"**Ranged Crit:** {ranged_crit}")
        lines.append(f"**Ranged Haste:** {ranged_haste}")
        lines.append(f"**Spell Crit:** {spell_crit}")
        lines.append(f"**Spell Haste:** {spell_haste}")
        lines.append(f"**Mastery:** {mastery}")

        lines.append("")
        lines.append(f"**Mana Regen (ooc):** {mana_regen}")
        lines.append(f"**Mana Regen (combat):** {mana_regen_combat}")

        embed = discord.Embed(
            title=f"{character.title()} – {realm.title()} ({region.upper()}) [{game.capitalize()}]",
            description="\n".join([x for x in lines if x is not None]),
            color=await ctx.embed_color(),
        )
        await ctx.send(embed=embed, ephemeral=bool(ctx.interaction))

    # ---------- Autocomplete ----------
    @charinfo.autocomplete("region")
    async def ac_region(self, interaction: discord.Interaction, current: str):
        cur = (current or "").lower()
        opts = [(r, r.lower()) for r in AC_REGIONS if r.lower() in {"eu", "us", "kr", "tw"}]
        return [app_commands.Choice(name=name, value=val) for name, val in opts if cur in val][:25]

    @charinfo.autocomplete("realm")
    async def ac_realm(self, interaction: discord.Interaction, current: str):
        sel_region = (getattr(interaction.namespace, "region", "") or "").upper()
        cur = (current or "").lower()
        out: List[str] = []
        for realm_name, realm_regions in AC_REALMS.items():
            if sel_region and sel_region not in realm_regions:
                continue
            if cur in realm_name.lower():
                out.append(realm_name)
        return [app_commands.Choice(name=r, value=r) for r in out[:25]]

    @charinfo.autocomplete("locale")
    async def ac_locale(self, interaction: discord.Interaction, current: str):
        cur = (current or "").lower()
        display = {"de":"Deutsch","en":"English","fr":"Français","es":"Español","it":"Italiano","pt":"Português","ru":"Русский"}
        pairs = []
        for short, full in AC_LANG_CODES.items():
            label = display.get(short, short)
            pairs.append((f"{label} ({full})", full))
            pairs.append((f"{label} ({short})", short))
        return [app_commands.Choice(name=l, value=v) for l, v in pairs if cur in l.lower() or cur in v.lower()][:25]

async def setup(bot: Red):
    await bot.add_cog(CharInfo(bot))
