import discord
from discord import app_commands
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from datetime import datetime, timezone
import io
import csv
import asyncio
import os
import re

try:
    import aiohttp
except ImportError:
    aiohttp = None

ONLINE_STATES = {discord.Status.online, discord.Status.idle, discord.Status.dnd}
DATE_FORMATS = ["%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"]

def _parse_date(s: str):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None

def _out_date(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y")

def _slugify_realm(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-{2,}", "-", s).strip("-")

def _slugify_char(s: str) -> str:
    s = s.strip().lower()
    s = (s.replace("ä","a").replace("ö","o").replace("ü","u").replace("ß","ss"))
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-{2,}", "-", s).strip("-")

class GuildTools(commands.Cog):
    """Cog: Tools für WoW-Gilden – Export, Abwesenheiten & /whois (ENV-first)."""

    __author__ = "Domekologe"
    __version__ = "1.3.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xD0DE2025, force_registration=True)
        self.config.register_guild(
            last_seen={},
            wow_default_region="eu",
            wow_default_realm=""
        )
        self.config.register_global(
            blizz_client_id="",
            blizz_client_secret="",
            blizz_token="",
            blizz_token_expires_at=0
        )
        self._abs_lock = asyncio.Lock()
        # In-Memory Token Cache (prozesslokal)
        self._token_mem = ""
        self._token_mem_exp = 0

    # ---------- Presence Tracking ----------
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if not after.guild:
            return
        intents = getattr(self.bot, "intents", None)
        if not intents or not intents.presences:
            return
        became_online = after.status in ONLINE_STATES and before.status != after.status
        became_offline = after.status is discord.Status.offline and before.status != after.status
        if not (became_online or became_offline):
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        data = await self.config.guild(after.guild).last_seen()
        data[str(after.id)] = now_iso
        await self.config.guild(after.guild).last_seen.set(data)

    # ---------- /export-userlist ----------
    @app_commands.command(name="export-userlist", description="Exportiert alle User in eine CSV.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def export_userlist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("Dieser Befehl muss in einer Guild ausgeführt werden.", ephemeral=True)
        members = []
        try:
            async for m in guild.fetch_members(limit=None):
                members.append(m)
        except discord.Forbidden:
            return await interaction.followup.send(
                "Mir fehlen Berechtigungen, um Mitglieder zu lesen. Bitte gib mir **Mitglieder anzeigen** (View Guild Members).",
                ephemeral=True
            )
        last_seen_map = await self.config.guild(guild).last_seen()
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\n")
        w.writerow(["UserID", "Username", "Name_Auf_Server", "Rolle(n)", "Mitglied_Seit", "Zuletzt_Online"])
        for m in members:
            w.writerow([
                str(m.id),
                m.name,
                m.display_name,
                ", ".join([r.name for r in m.roles if r.name != "@everyone"]) or "",
                m.joined_at.astimezone(timezone.utc).isoformat() if m.joined_at else "",
                last_seen_map.get(str(m.id), "unbekannt"),
            ])
        buf.seek(0)
        file = discord.File(io.BytesIO(buf.getvalue().encode("utf-8-sig")), filename=f"user_export_{guild.id}.csv")
        await interaction.followup.send("Hier ist dein Export (nur für dich sichtbar).", file=file, ephemeral=True)

    # ---------- Abwesenheiten ----------
    @app_commands.command(name="add-absence", description="Trage eine Abwesenheit ein (DD-MM-YYYY / DD.MM.YYYY / DD/MM/YYYY).")
    @app_commands.describe(von="Startdatum", bis="Enddatum")
    @app_commands.guild_only()
    async def add_absence(self, interaction: discord.Interaction, von: str, bis: str):
        start, end = _parse_date(von), _parse_date(bis)
        if not start:
            return await interaction.response.send_message("❌ Ungültiges **von**-Datum.", ephemeral=True)
        if not end:
            return await interaction.response.send_message("❌ Ungültiges **bis**-Datum.", ephemeral=True)
        if end < start:
            return await interaction.response.send_message("❌ **bis** darf nicht vor **von** liegen.", ephemeral=True)
        if (end - start).days > 365:
            return await interaction.response.send_message("❌ Abwesenheiten dürfen max. 365 Tage umfassen.", ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Dieser Befehl muss in einer Guild ausgeführt werden.", ephemeral=True)

        data_dir = cog_data_path(raw_name=self.__class__.__name__)
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / f"absences_{guild.id}.txt"

        line = ";".join([
            str(interaction.user.id),
            interaction.user.name,
            interaction.user.display_name,
            _out_date(start),
            _out_date(end),
        ]) + "\n"

        async with self._abs_lock:
            new_file = not path.exists()
            def _write():
                with open(path, "a", encoding="utf-8") as f:
                    if new_file:
                        f.write("UserID;Username;Name auf Server;Von;Bis\n")
                    f.write(line)
            await asyncio.to_thread(_write)

        await interaction.response.send_message(
            f"✅ Abwesenheit gespeichert für **{interaction.user.mention}**\n"
            f"• Von: **{_out_date(start)}**\n"
            f"• Bis: **{_out_date(end)}**",
            ephemeral=True,
        )

    @app_commands.command(name="list-absence", description="Zeigt deine Abwesenheiten (ephemeral).")
    @app_commands.guild_only()
    async def list_absence(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("Dieser Befehl muss in einer Guild ausgeführt werden.", ephemeral=True)
        data_dir = cog_data_path(raw_name=self.__class__.__name__)
        path = data_dir / f"absences_{guild.id}.txt"
        if not path.exists():
            return await interaction.followup.send("Keine Abwesenheiten gefunden.", ephemeral=True)

        uid = str(interaction.user.id)
        async with self._abs_lock:
            def _read_rows():
                out = []
                with open(path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i == 0:  # Header
                            continue
                        parts = line.rstrip("\n").split(";")
                        if len(parts) >= 5 and parts[0] == uid:
                            out.append(parts)
                return out
            rows = await asyncio.to_thread(_read_rows)

        if not rows:
            return await interaction.followup.send("Du hast keine Abwesenheiten hinterlegt.", ephemeral=True)

        desc = "\n".join(f"• **{r[3]}** → **{r[4]}** (als *{r[2]}*)" for r in rows)
        embed = discord.Embed(title="Deine Abwesenheiten", description=desc, color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="get-absence", description="CSV mit allen Abwesenheiten (nur Mods).")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def get_absence(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("Dieser Befehl muss in einer Guild ausgeführt werden.", ephemeral=True)
        data_dir = cog_data_path(raw_name=self.__class__.__name__)
        path = data_dir / f"absences_{guild.id}.txt"
        if not path.exists():
            return await interaction.followup.send("Keine Abwesenheiten gefunden.", ephemeral=True)

        async with self._abs_lock:
            def _read_all():
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            content = await asyncio.to_thread(_read_all)

        out_bytes = ("\ufeff" + content).encode("utf-8")
        file = discord.File(io.BytesIO(out_bytes), filename=f"absences_{guild.id}.csv")
        await interaction.followup.send("Hier ist die Abwesenheitsliste (nur für dich sichtbar).", file=file, ephemeral=True)

    # ---------- Blizzard API: ENV-first Credentials ----------
    @commands.command(name="setblizzard")
    @commands.is_owner()
    async def set_blizzard_credentials(self, ctx: commands.Context, client_id: str, client_secret: str):
        """Owner-only: Setzt Blizzard API Client-ID/-Secret (Fallback, wenn ENV nicht genutzt wird)."""
        await self.config.blizz_client_id.set(client_id)
        await self.config.blizz_client_secret.set(client_secret)
        await self.config.blizz_token.set("")
        await self.config.blizz_token_expires_at.set(0)
        # In-Memory ebenfalls leeren
        self._token_mem = ""
        self._token_mem_exp = 0
        await ctx.tick()

    @commands.command(name="clearblizzard")
    @commands.is_owner()
    async def clear_blizzard_credentials(self, ctx: commands.Context):
        """Owner-only: Löscht Blizzard API Credentials aus der Config."""
        await self.config.blizz_client_id.set("")
        await self.config.blizz_client_secret.set("")
        await self.config.blizz_token.set("")
        await self.config.blizz_token_expires_at.set(0)
        self._token_mem = ""
        self._token_mem_exp = 0
        await ctx.tick()

    @app_commands.command(name="set-wow-defaults", description="Setzt Default-Region/Realm für /whois.")
    @app_commands.describe(region="eu/us/kr/tw", realm="Realmname (z. B. 'Blackmoore')")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def set_wow_defaults(self, interaction: discord.Interaction, region: str, realm: str):
        region = region.lower()
        if region not in {"eu", "us", "kr", "tw"}:
            return await interaction.response.send_message("Region muss **eu/us/kr/tw** sein.", ephemeral=True)
        await self.config.guild(interaction.guild).wow_default_region.set(region)
        await self.config.guild(interaction.guild).wow_default_realm.set(realm.strip())
        await interaction.response.send_message(f"✅ Defaults gesetzt: Region **{region}**, Realm **{realm.strip()}**", ephemeral=True)

    async def _get_token(self) -> str:
        """ENV-first Tokenbeschaffung. Wenn ENV genutzt wird, Token nur im Speicher; sonst zusätzlich in Config."""
        if aiohttp is None:
            raise RuntimeError("aiohttp nicht installiert.")

        # 1) ENV zuerst
        env_id = os.getenv("BLIZZARD_CLIENT_ID") or ""
        env_secret = os.getenv("BLIZZARD_CLIENT_SECRET") or ""
        use_env = bool(env_id and env_secret)

        # 2) Fallback: Config
        if not use_env:
            env_id = await self.config.blizz_client_id()
            env_secret = await self.config.blizz_client_secret()
            if not (env_id and env_secret):
                raise RuntimeError("Blizzard API Credentials fehlen. Setze ENV oder nutze `[p]setblizzard <id> <secret>`.")

        now = int(datetime.now(timezone.utc).timestamp())
        # In-Memory Cache reicht meist
        if self._token_mem and now < self._token_mem_exp - 60:
            return self._token_mem

        # Wenn Config-Creds verwendet werden, schauen wir zusätzlich nach einem noch gültigen Token in der Config
        if not use_env:
            cfg_token = await self.config.blizz_token()
            cfg_exp = await self.config.blizz_token_expires_at()
            if cfg_token and now < cfg_exp - 60:
                self._token_mem = cfg_token
                self._token_mem_exp = cfg_exp
                return cfg_token

        # Neues Token holen
        token_url = "https://oauth.battle.net/token"
        data = {"grant_type": "client_credentials"}

        async with aiohttp.ClientSession() as sess:
            async with sess.post(token_url, data=data, auth=aiohttp.BasicAuth(env_id, env_secret)) as r:
                if r.status != 200:
                    text = await r.text()
                    raise RuntimeError(f"Token-Request fehlgeschlagen ({r.status}): {text}")
                js = await r.json()

        token = js.get("access_token", "")
        expires_in = int(js.get("expires_in", 0))
        exp = now + max(0, expires_in)

        # Cache immer in Memory …
        self._token_mem = token
        self._token_mem_exp = exp
        # … und nur bei Config-Creds zusätzlich persistent speichern
        if not use_env:
            await self.config.blizz_token.set(token)
            await self.config.blizz_token_expires_at.set(exp)

        return token

    async def _get_profile(self, region: str, realm: str, charname: str, locale: str = "de_DE"):
        token = await self._get_token()
        realm_slug = _slugify_realm(realm)
        char_slug = _slugify_char(charname)
        base = f"https://{region}.api.blizzard.com"
        ns = f"profile-classic-{region}"
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession(headers=headers) as sess:
            params = {"namespace": ns, "locale": locale}
            prof_url = f"{base}/profile/wow/character/{realm_slug}/{char_slug}"
            async with sess.get(prof_url, params=params) as r:
                if r.status == 404:
                    return None
                if r.status != 200:
                    raise RuntimeError(f"Profil-Request fehlgeschlagen ({r.status}).")
                prof = await r.json()
            equip_url = f"{base}/profile/wow/character/{realm_slug}/{char_slug}/equipment"
            ilvl = None
            async with sess.get(equip_url, params=params) as r2:
                if r2.status == 200:
                    eq = await r2.json()
                    ilvl = eq.get("equipped_item_level") or eq.get("average_item_level")
        prof["_equipped_ilvl"] = ilvl
        return prof

    @app_commands.command(name="whois", description="Zeigt WoW-Charakterinfos (Level, Klasse, Gilde, iLvl wenn möglich).")
    @app_commands.describe(charname="Charaktername", realm="Optionaler Realm (sonst Gilden-Default)")
    @app_commands.guild_only()
    async def whois(self, interaction: discord.Interaction, charname: str, realm: str | None = None):
        await interaction.response.defer(ephemeral=True)
        gconf = self.config.guild(interaction.guild)
        region = (await gconf.wow_default_region()) or "eu"
        def_realm = (await gconf.wow_default_realm()) or ""
        realm_use = realm.strip() if realm else def_realm
        if not realm_use:
            return await interaction.followup.send("Bitte Realm angeben oder `/set-wow-defaults` setzen.", ephemeral=True)

        try:
            prof = await self._get_profile(region, realm_use, charname, locale="de_DE")
        except Exception as e:
            return await interaction.followup.send(f"❌ Fehler bei der Blizzard API: {e}", ephemeral=True)

        if not prof:
            return await interaction.followup.send("❌ Charakter nicht gefunden (Name/Realm/Region prüfen).", ephemeral=True)

        name = prof.get("name", charname)
        realm_name = prof.get("realm", {}).get("name", realm_use)
        level = prof.get("level", "?")
        char_class = prof.get("character_class", {}).get("name", "Unbekannt")
        race = prof.get("race", {}).get("name", "Unbekannt")
        guild_name = prof.get("guild", {}).get("name", "—")
        ilvl = prof.get("_equipped_ilvl")
        faction = prof.get("faction", {}).get("name", "")
        last_login = prof.get("last_login_timestamp")
        last_login_str = ""
        if isinstance(last_login, int):
            dt = datetime.fromtimestamp(last_login/1000, tz=timezone.utc)
            last_login_str = dt.strftime("%d.%m.%Y %H:%M UTC")

        embed = discord.Embed(title=f"{name} @ {realm_name}", color=discord.Color.gold())
        embed.add_field(name="Level / Klasse", value=f"{level} / {char_class}", inline=True)
        embed.add_field(name="Rasse / Fraktion", value=f"{race} / {faction or '—'}", inline=True)
        embed.add_field(name="Gilde", value=guild_name or "—", inline=True)
        if ilvl:
            embed.add_field(name="Ø Itemlevel", value=str(ilvl), inline=True)
        if last_login_str:
            embed.add_field(name="Zuletzt eingeloggt", value=last_login_str, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: Red):
    await bot.add_cog(GuildTools(bot))
