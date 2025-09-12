# WoWTools/talentcheck.py
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Literal, Dict, Optional

import discord
from discord import app_commands
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n, set_contextual_locales_from_guild

# zentrale Tabellen aus autocomplete.py
from .autocomplete import (
    REGIONS,
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

def _wowhead_spell(spell_id: int) -> str:
    return f"https://www.wowhead.com/mop-classic/spell={spell_id}"

# -------- OAuth Cache (lokal) --------
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

async def _fetch_specializations(
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
    url = f"https://{host}/profile/wow/character/{realm}/{character}/specializations"
    params = {"namespace": namespace, "locale": locale}
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, headers=headers) as resp:
            js = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"{resp.status}: {js}")
            return js

@cog_i18n(_)
class TalentCheck(commands.Cog):
    """Zeigt aktive Talente und aktive Glyphen eines Charakters (Classic/Retail)."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot

    @commands.hybrid_command(name="talentcheck")
    @app_commands.describe(
        region="Region (eu/us/kr/tw)",
        realm="Realm (mit Bindestrich statt Leerzeichen, z. B. everlook)",
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
    async def talentcheck(
        self,
        ctx: commands.Context,
        region: str,
        realm: str,
        character: str,
        game: Literal["classic", "retail"] = "classic",
        locale: str = "en",
        private: bool = True,
    ):
        if ctx.interaction:
            await set_contextual_locales_from_guild(self.bot, ctx.guild)
        region = region.lower()
        locale = _resolve_locale(locale)
        # Slugs
        realm_slug = realm.lower().replace(" ", "-")
        char_slug = character.lower()

        try:
            await ctx.defer(ephemeral=private)
        except Exception:
            pass

        try:
            data = await _fetch_specializations(
                self, region=region, realm=realm_slug, character=char_slug, game=game, locale=locale
            )
        except Exception as e:
            return await ctx.send(f"Fehler beim Abrufen der Talente: {e}", ephemeral=bool(ctx.interaction))

        active_spec = (data.get("active_specialization") or {}).get("name")
        specs = data.get("specializations") or []
        spec_lines: List[str] = []

        for spec in specs:
            spec_name = spec.get("specialization_name") or (spec.get("specialization") or {}).get("name") or "?"
            header = f"**{spec_name}**" + ("  *(aktiv)*" if active_spec and spec_name == active_spec else "")
            spec_lines.append(header)

            # Talente
            talents = spec.get("talents") or []
            if talents:
                for t in talents:
                    tt = t.get("spell_tooltip") or {}
                    spell = (tt.get("spell") or {})
                    spell_name = spell.get("name") or (t.get("talent") or {}).get("name") or "?"
                    spell_id = spell.get("id")
                    if spell_id:
                        spec_lines.append(f"`└──` **Talent:** [{spell_name}]({_wowhead_spell(spell_id)})")
                    else:
                        spec_lines.append(f"`└──` **Talent:** {spell_name}")

        # Aktive Glyphen: aus specialization_groups is_active == true
        glyph_lines: List[str] = []
        for grp in data.get("specialization_groups", []) or []:
            if grp.get("is_active"):
                glyphs = grp.get("glyphs") or []
                if glyphs:
                    glyph_lines.append("**Aktive Glyphen**")
                    for g in glyphs:
                        name = g.get("name") or "?"
                        glyph_lines.append(f"`└──` {name}")
                break  # nur die aktive Gruppe

        if not spec_lines and not glyph_lines:
            return await ctx.send("Keine Talent-/Glyphen-Daten gefunden.", ephemeral=bool(ctx.interaction))

        embed = discord.Embed(
            title=f"{character.title()} – {realm.title()} ({region.upper()}) [{game.capitalize()}]",
            description="\n".join(spec_lines + ([""] if spec_lines and glyph_lines else []) + glyph_lines),
            color=await ctx.embed_color(),
        )
        ephemeral = private if ctx.interaction else False
        await ctx.send(embed=embed, ephemeral=ephemeral)

    # ---------- Autocomplete ----------
    @talentcheck.autocomplete("region")
    async def ac_region(self, interaction: discord.Interaction, current: str):
        cur = (current or "").lower()
        opts = [(r, r.lower()) for r in REGIONS if r.lower() in {"eu", "us", "kr", "tw"}]
        return [app_commands.Choice(name=name, value=val) for name, val in opts if cur in val][:25]

    @talentcheck.autocomplete("realm")
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

    @talentcheck.autocomplete("locale")
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
    await bot.add_cog(TalentCheck(bot))
