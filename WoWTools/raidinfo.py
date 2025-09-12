# WoWTools/raidinfo.py
import aiohttp
import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

import discord
from discord import app_commands
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n, set_contextual_locales_from_guild

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

# -------- OAuth Cache --------
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

# -------- Fetch --------
async def _fetch_achv_statistics(
    self,
    *,
    region: str,
    realm: str,
    character: str,
    game: str = "classic",
    locale: str = "en_US",
) -> dict:
    host = _API_HOST.get(region, "eu.api.blizzard.com")
    token = await _get_access_token(self, region)
    namespace = f"profile-{region}" if game == "retail" else f"profile-classic-{region}"
    url = f"https://{host}/profile/wow/character/{realm}/{character}/achievements/statistics"
    params = {"namespace": namespace, "locale": locale}
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, headers=headers) as resp:
            js = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"{resp.status}: {js}")
            return js

# -------- Helpers --------
# Bekannte MoP-Raids
_MOP_RAIDS = {
    "Mogu'shan Vaults",
    "Heart of Fear",
    "Terrace of Endless Spring",
    "Throne of Thunder",
    "Siege of Orgrimmar",
}

# Regex: "<Boss> kills (10-player Normal <Raid>)"
_RE_RAID_LINE = re.compile(
    r"^(?P<boss>.+?) kills \((?P<mode>.+?) (?P<raid>.+?)\)$"
)

def _collect_all_mop_stats(js: dict) -> List[dict]:
    """Nimmt nur Dungeons & Raids → Mists of Pandaria."""
    out: List[dict] = []
    for cat in js.get("categories") or []:
        if (cat.get("name") or "").lower() != "dungeons & raids":
            continue
        for sub in cat.get("sub_categories") or []:
            if (sub.get("name") or "").lower() == "mists of pandaria":
                # Direkt enthaltene Stats
                out.extend(sub.get("statistics") or [])
                # Falls Unter-Unterkategorien existieren:
                def walk(inner):
                    out.extend(inner.get("statistics") or [])
                    for sc in inner.get("sub_categories") or []:
                        walk(sc)
                for sc in sub.get("sub_categories") or []:
                    walk(sc)
                return out
    return out

def _parse_raid_stat_name(name: str) -> Optional[Tuple[str, str, str]]:
    """
    Gibt (boss, raid, diff) zurück oder None.
    diff ∈ {"nhc","hc"} basierend auf "Normal"/"Heroic". 10/25 wird bewusst nicht getrennt.
    """
    if not name:
        return None
    m = _RE_RAID_LINE.match(name)
    if not m:
        return None
    boss = m.group("boss").strip()
    mode = m.group("mode").strip()      # z. B. "10-player Normal"
    raid = m.group("raid").strip()      # z. B. "Mogu'shan Vaults"

    # Nur MoP-Raids berücksichtigen
    if raid not in _MOP_RAIDS:
        return None

    diff = "hc" if "heroic" in mode.lower() else "nhc"
    return boss, raid, diff

def _group_by_raid(stats: List[dict], only_extension: Optional[str]) -> Dict[str, Dict[str, Dict[str, int]]]:
    """
    Rückgabe-Struktur:
    {
      "<Raid>": {
        "<Boss>": {"nhc": int, "hc": int}
      }
    }
    """
    raids: Dict[str, Dict[str, Dict[str, int]]] = {}
    ext = (only_extension or "").strip().lower() if only_extension else ""

    for st in stats:
        name = st.get("name") or ""
        q = st.get("quantity")
        if not isinstance(q, (int, float)):
            continue
        if isinstance(q, float) and q.is_integer():
            q = int(q)

        parsed = _parse_raid_stat_name(name)
        if not parsed:
            continue
        boss, raid, diff = parsed

        # optionaler Extension-Filter (Raidname enthält extension)
        if ext and ext not in raid.lower():
            continue

        raids.setdefault(raid, {})
        raids[raid].setdefault(boss, {"nhc": 0, "hc": 0})
        raids[raid][boss][diff] += int(q)

    # Nach Raidname sortieren, innerhalb nach Bossname
    sorted_raids: Dict[str, Dict[str, Dict[str, int]]] = {}
    for raid in sorted(raids.keys()):
        bosses = raids[raid]
        sorted_bosses = dict(sorted(bosses.items(), key=lambda kv: kv[0].lower()))
        sorted_raids[raid] = sorted_bosses
    return sorted_raids

def _format_embed_text(grouped: Dict[str, Dict[str, Dict[str, int]]]) -> str:
    lines: List[str] = []
    for raid, bosses in grouped.items():
        lines.append(f"**{raid}**")
        if not bosses:
            lines.append("_Keine Bossdaten_")
            continue
        for boss, counts in bosses.items():
            nhc = counts.get("nhc", 0)
            hc = counts.get("hc", 0)
            lines.append(f"- {boss}\n  `nhc => {nhc}`\n  `hc  => {hc}`")
        lines.append("")  # Leerzeile zwischen Raids
    text = "\n".join(lines).strip()
    # Discord-Softlimit: kürzen falls zu lang
    return text[:3800]  # genug Luft für Titel/Farbe

@cog_i18n(_)
class RaidInfo(commands.Cog):
    """Listet MoP-Raids → Bosse mit Kills nach Schwierigkeitsgrad (nhc/hc)."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot

    @commands.hybrid_command(name="raidinfo")
    @app_commands.describe(
        region="Region (eu/us/kr/tw)",
        realm="Realm (mit Bindestrich statt Leerzeichen)",
        character="Charaktername",
        game="Classic (MoP Classic) oder Retail",
        locale="Locale (z. B. de oder de_DE, en oder en_US)",
        extension="Optionaler Filter (Raid-Name, z. B. 'Mogu'shan Vaults'). Leer = alle MoP-Raids.",
    )
    @app_commands.choices(
        game=[
            app_commands.Choice(name="Classic", value="classic"),
            app_commands.Choice(name="Retail", value="retail"),
        ]
    )
    async def raidinfo(
        self,
        ctx: commands.Context,
        region: str,
        realm: str,
        character: str,
        game: str,
        locale: str = "en",
        extension: Optional[str] = None,
        private: bool = True,
    ):
        if ctx.interaction:
            await set_contextual_locales_from_guild(self.bot, ctx.guild)

        region = (region or "").lower()
        locale = _resolve_locale(locale)
        realm_slug = realm.lower().replace(" ", "-")
        char_slug = character.lower()

        try:
            await ctx.defer(ephemeral=private)
        except Exception:
            pass

        try:
            js = await _fetch_achv_statistics(
                self, region=region, realm=realm_slug, character=char_slug, game=game, locale=locale
            )
        except Exception as e:
            return await ctx.send(f"Fehler beim Abrufen der Achievements-Statistiken: {e}", ephemeral=bool(ctx.interaction))

        mop_stats = _collect_all_mop_stats(js)
        if not mop_stats:
            return await ctx.send("Keine MoP-Dungeon/Raid-Statistiken gefunden.", ephemeral=bool(ctx.interaction))

        grouped = _group_by_raid(mop_stats, extension)
        if not grouped:
            flt = extension or "—"
            return await ctx.send(f"Keine passenden Raid-Einträge für Filter **{flt}**.", ephemeral=bool(ctx.interaction))

        text = _format_embed_text(grouped)
        embed = discord.Embed(
            title=f"{character.title()} – {realm.title()} ({region.upper()}) [{game.capitalize()}] – Mists of Pandaria",
            description=text,
            color=await ctx.embed_color(),
        )
        ephemeral = private if ctx.interaction else False
        await ctx.send(embed=embed, ephemeral=ephemeral)

    # ---------- Autocomplete ----------
    @raidinfo.autocomplete("region")
    async def ac_region(self, interaction: discord.Interaction, current: str):
        cur = (current or "").lower()
        opts = [(r, r.lower()) for r in REGIONS if r.lower() in {"eu", "us", "kr", "tw"}]
        # startswith priorisieren
        def prio(t):
            name, val = t
            return (0 if val.startswith(cur) or name.lower().startswith(cur) else 1, val)
        opts.sort(key=prio)
        return [app_commands.Choice(name=name, value=val) for name, val in opts if not cur or cur in val][:25]

    @raidinfo.autocomplete("realm")
    async def ac_realm(self, interaction: discord.Interaction, current: str):
        sel_region = (getattr(interaction.namespace, "region", "") or "").upper()
        cur = (current or "").lower()
        out: List[str] = []
        for realm_name, realm_regions in AC_REALMS.items():
            if sel_region and sel_region not in realm_regions:
                continue
            if not cur or cur in realm_name.lower():
                out.append(realm_name)
        return [app_commands.Choice(name=r, value=r) for r in out[:25]]

    @raidinfo.autocomplete("locale")
    async def ac_locale(self, interaction: discord.Interaction, current: str):
        cur = (current or "").lower()
        display = {"de":"Deutsch","en":"English","fr":"Français","es":"Español","it":"Italiano","pt":"Português","ru":"Русский"}
        pairs = []
        for short, full in AC_LANG_CODES.items():
            label = display.get(short, short)
            pairs.append((f"{label} ({full})", full))
            pairs.append((f"{label} ({short})", short))
        return [app_commands.Choice(name=l, value=v) for l, v in pairs if not cur or cur in l.lower() or cur in v.lower()][:25]

async def setup(bot: Red):
    await bot.add_cog(RaidInfo(bot))
