# -*- coding: utf-8 -*-
# membercharsetup.py
# Red-DiscordBot Cog: New-member setup & WoW character link
#
# Features:
# - /setup-newmember enabled:<bool> [role] [language: de|en]  (Mods/Admins)
# - Automatische DM bei Rollenvergabe (nur neue Role-Zuweisung)
# - Erfragt Main-Char, speichert (optional prüft WoW API Gildenmitgliedschaft)
# - /getmemberchars  -> schickt DM-Liste
# - /setmainchar, /settwinkchar, /removetwink, /removemainchar (mit Dropdowns)
# - /charrequest <User> (Mods): erneute Abfrage per DM
# - /setwgguild (Mods): Region/Realm/Gildenname
# - /setwowapi (Mods): ClientID/Secret pro Region + Toggle aktiv
# - Extra-Datei-Export nach jeder Änderung (/data/membercharsetup/members.json)

from __future__ import annotations
from .dashboard_integration import DashboardIntegration


import asyncio
import json
import time
import re
from typing import Dict, List, Optional, Tuple

import discord
from discord import app_commands
from redbot.core import commands, Config, checks, data_manager
from redbot.core.bot import Red

import aiohttp




LANGS = ("de", "en")

def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s

def _t(lang: str, key: str, **fmt) -> str:
    de = {
        "welcome": "Herzlich Willkommen bei {guild}!\nBitte schreibe mir den Namen deines Hauptcharakters!",
        "saved_main": "✅ Dein Hauptcharakter **{char}** wurde gespeichert.",
        "ask_main_retry": "⚠️ Ich konnte deinen Charakter nicht in der Gilde **{guild}** finden.\nBist du sicher, dass der Name korrekt ist? Antworte erneut mit deinem **Hauptchar**.",
        "dm_failed": "⚠️ Konnte keine DM senden. Bitte erlaube DMs oder schreibe mir direkt.",
        "no_chars": "Keine Charaktere gespeichert.",
        "sent_dm": "📬 Ich habe dir eine DM geschickt.",
        "twink_added": "✅ Twink **{char}** hinzugefügt.",
        "twink_exists": "⚠️ Dieser Twink ist bereits gespeichert.",
        "main_set": "✅ Dein Hauptcharakter wurde auf **{char}** gesetzt.",
        "removed_twink": "🗑️ Twink **{char}** entfernt.",
        "no_twink": "⚠️ Dieser Twink existiert nicht.",
        "removed_main": "🗑️ Hauptchar **{char}** entfernt.",
        "no_main": "⚠️ Du hast aktuell keinen Hauptchar gespeichert.",
        "cfg_saved": "✅ Setup gespeichert: Enabled={enabled}, Role={role}, Language={lang}",
        "guild_saved": "✅ Gilden-Einstellungen gespeichert: Region={region}, Realm={realm}, Gilde={guild}",
        "api_saved": "✅ WoW-API konfiguriert (aktiv={active}). Client-ID/Secret gespeichert.",
        "api_missing": "⚠️ Der WoW-API-Abgleich ist aktiv, aber es fehlen API-Credentials oder Gildenangaben.",
        "not_mod": "❌ Dafür fehlt dir die Berechtigung.",
        "select_twink_placeholder": "Wähle einen Twink zum Entfernen…",
        "select_main_placeholder": "Wähle deinen Hauptchar zum Entfernen…",
        "charrequest_sent": "✅ Anfrage an {user} gesendet.",
    }
    en = {
        "welcome": "Welcome to {guild}!\nPlease tell me the name of your main character!",
        "saved_main": "✅ Your main character **{char}** has been saved.",
        "ask_main_retry": "⚠️ I couldn't find your character in the guild **{guild}**.\nAre you sure the name is correct? Please reply again with your **main**.",
        "dm_failed": "⚠️ I couldn't DM you. Please enable DMs or message me directly.",
        "no_chars": "No characters stored.",
        "sent_dm": "📬 I sent you a DM.",
        "twink_added": "✅ Added twink **{char}**.",
        "twink_exists": "⚠️ That twink is already stored.",
        "main_set": "✅ Your main character has been set to **{char}**.",
        "removed_twink": "🗑️ Removed twink **{char}**.",
        "no_twink": "⚠️ That twink does not exist.",
        "removed_main": "🗑️ Removed main **{char}**.",
        "no_main": "⚠️ You don't have a main saved.",
        "cfg_saved": "✅ Setup saved: Enabled={enabled}, Role={role}, Language={lang}",
        "guild_saved": "✅ Guild settings saved: Region={region}, Realm={realm}, Guild={guild}",
        "api_saved": "✅ WoW API configured (active={active}). Client ID/Secret saved.",
        "api_missing": "⚠️ WoW API check is active, but API credentials or guild settings are missing.",
        "not_mod": "❌ You lack permission for this.",
        "select_twink_placeholder": "Choose a twink to remove…",
        "select_main_placeholder": "Choose your main to remove…",
        "charrequest_sent": "✅ Sent a request to {user}.",
    }
    table = de if lang == "de" else en
    return table[key].format(**fmt)


class RemoveTwinkSelect(discord.ui.Select):
    def __init__(self, user_twinks: List[str], lang: str):
        opts = [discord.SelectOption(label=t, value=t) for t in user_twinks[:25]]
        placeholder = _t(lang, "select_twink_placeholder")
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        view: "RemoveTwinkView" = self.view  # type: ignore
        await view.handle_choice(interaction, self.values[0])


class RemoveTwinkView(discord.ui.View):
    def __init__(self, cog: "MemberCharSetup", user: discord.User, lang: str, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user = user
        self.lang = lang

    async def handle_choice(self, interaction: discord.Interaction, twink: str):
        twinks = await self.cog.config.user(self.user).twinks()
        if twink in twinks:
            twinks.remove(twink)
            await self.cog.config.user(self.user).twinks.set(twinks)
            await self.cog._dump_all_members()
            await interaction.response.edit_message(content=_t(self.lang, "removed_twink", char=twink), view=None)
        else:
            await interaction.response.edit_message(content=_t(self.lang, "no_twink"), view=None)


class RemoveMainSelect(discord.ui.Select):
    def __init__(self, main: str, lang: str):
        opts = [discord.SelectOption(label=main, value=main)]
        placeholder = _t(lang, "select_main_placeholder")
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        view: "RemoveMainView" = self.view  # type: ignore
        await view.handle_choice(interaction, self.values[0])


class RemoveMainView(discord.ui.View):
    def __init__(self, cog: "MemberCharSetup", user: discord.User, lang: str, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user = user
        self.lang = lang

    async def handle_choice(self, interaction: discord.Interaction, main: str):
        current = await self.cog.config.user(self.user).main()
        if current and current.lower() == main.lower():
            await self.cog.config.user(self.user).main.set(None)
            await self.cog._dump_all_members()
            await interaction.response.edit_message(content=_t(self.lang, "removed_main", char=main), view=None)
        else:
            await interaction.response.edit_message(content=_t(self.lang, "no_main"), view=None)


class MemberCharSetup(DashboardIntegration, commands.Cog):
    """Setup new members and link their WoW characters."""

    __author__ = "Domekologe"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xD0DECA7, force_registration=True)
        # Guild-wide
        self.config.register_guild(
            enabled=False,
            role_id=None,
            language="de",
            wow_region="eu",      # us | eu | kr | tw
            wow_realm="",
            wow_guild="",
            wow_api_enabled=True,  # toggle for API check
        )
        # User specific
        self.config.register_user(main=None, twinks=[])
        # Global (bot-wide) creds per region
        self.config.register_global(
            wow_api={
                "eu": {"client_id": None, "client_secret": None},
                "us": {"client_id": None, "client_secret": None},
                "kr": {"client_id": None, "client_secret": None},
                "tw": {"client_id": None, "client_secret": None},
            },
            wow_tokens={},  # cache: {region: {"token": "...", "expires_at": 1234567890}}
        )
        # data file path
        self._data_path = data_manager.cog_data_path(raw_name="membercharsetup")
        self._data_path.mkdir(parents=True, exist_ok=True)
        self._members_file = self._data_path / "members.json"
        self._session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------- Helpers -------------

    async def _dump_all_members(self):
        # Export readable file by guild with usernames
        payload: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
        # build per guild
        for guild in self.bot.guilds:
            try:
                # Filter users present in this guild
                lines = {}
                for member in guild.members:
                    uconf = await self.config.user(member).all()
                    if uconf.get("main") or uconf.get("twinks"):
                        lines[str(member.id)] = {
                            "display_name": member.display_name,
                            "main": uconf.get("main"),
                            "twinks": uconf.get("twinks", []),
                        }
                if lines:
                    payload[str(guild.id)] = {
                        "guild_name": guild.name,
                        "members": lines,
                    }
            except Exception:
                continue

        try:
            with self._members_file.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # Don't crash the cog for I/O issues
            print(f"[MemberCharSetup] Failed to write members.json: {e}")

    async def _get_token(self, region: str) -> Optional[str]:
        # cached token?
        global_conf = await self.config.wow_tokens()
        now = int(time.time())
        cached = global_conf.get(region)
        if cached and cached.get("expires_at", 0) - 30 > now:
            return cached.get("token")

        creds = (await self.config.wow_api()).get(region, {})
        cid, csec = creds.get("client_id"), creds.get("client_secret")
        if not cid or not csec or not self._session:
            return None

        token_url = f"https://{region}.battle.net/oauth/token"
        data = {"grant_type": "client_credentials"}
        try:
            async with self._session.post(token_url, data=data, auth=aiohttp.BasicAuth(cid, csec), timeout=20) as r:
                if r.status != 200:
                    return None
                js = await r.json()
        except Exception:
            return None

        token = js.get("access_token")
        exp = js.get("expires_in", 0)
        if token:
            global_conf[region] = {"token": token, "expires_at": now + int(exp)}
            await self.config.wow_tokens.set(global_conf)
            return token
        return None

    async def _check_wow_guild(self, guild: discord.Guild, char_name: str) -> Optional[bool]:
        # Returns True/False if check possible, None if check not possible
        gconf = await self.config.guild(guild).all()
        if not gconf.get("wow_api_enabled", True):
            return None

        region = (gconf.get("wow_region") or "eu").lower()
        realm = gconf.get("wow_realm") or ""
        gname = gconf.get("wow_guild") or ""
        if not realm or not gname:
            return None
        token = await self._get_token(region)
        if not token or not self._session:
            return None

        realm_slug = _slugify(realm)
        guild_slug = _slugify(gname)
        # Guild roster endpoint (profile namespace)
        url = f"https://{region}.api.blizzard.com/data/wow/guild/{realm_slug}/{guild_slug}/roster"
        params = {"namespace": f"profile-{region}", "locale": "en_US", "access_token": token}

        try:
            async with self._session.get(url, params=params, timeout=20) as r:
                if r.status != 200:
                    return None
                js = await r.json()
        except Exception:
            return None

        want = char_name.strip().lower()
        try:
            members = js.get("members", [])
            for m in members:
                c = m.get("character", {}).get("name")
                if c and c.strip().lower() == want:
                    return True
            return False
        except Exception:
            return None

    async def _ask_for_main_via_dm(self, member: discord.Member, lang: str, gconf: dict) -> bool:
        # returns True if saved, False otherwise
        try:
            await member.send(_t(lang, "welcome", guild=member.guild.name))
        except discord.Forbidden:
            # DM closed
            try:
                await member.send(_t(lang, "dm_failed"))
            except Exception:
                pass
            return False
        except Exception:
            return False

        def check(m: discord.Message):
            return m.author.id == member.id and isinstance(m.channel, discord.DMChannel)

        # up to 2 attempts if guild-check fails
        attempts = 2 if gconf.get("wow_api_enabled", True) else 1

        for i in range(attempts):
            try:
                reply: discord.Message = await self.bot.wait_for("message", check=check, timeout=300.0)
            except asyncio.TimeoutError:
                return False

            char = reply.content.strip()
            # Optional check against WoW guild roster
            checked = await self._check_wow_guild(member.guild, char)
            if checked is True or checked is None:
                await self.config.user(member).main.set(char)
                await self._dump_all_members()
                try:
                    await member.send(_t(lang, "saved_main", char=char))
                except Exception:
                    pass
                return True
            else:
                # not found in guild, ask again once
                try:
                    await member.send(_t(lang, "ask_main_retry", guild=gconf.get("wow_guild") or member.guild.name))
                except Exception:
                    pass

        return False

    # ------------- Events -------------

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Only handle role gain for configured role
        if before.guild.id != after.guild.id:
            return
        gconf = await self.config.guild(after.guild).all()
        if not gconf.get("enabled") or not gconf.get("role_id"):
            return
        role = after.guild.get_role(gconf["role_id"])
        if not role:
            return
        # Trigger only when the role was newly added
        if role not in before.roles and role in after.roles:
            lang = gconf.get("language", "de")
            await self._ask_for_main_via_dm(after, lang, gconf)

    # ------------- Commands -------------

    @checks.mod_or_permissions(manage_guild=True)
    @commands.hybrid_command(name="setup-newmember")
    @app_commands.describe(enabled="Feature aktivieren/deaktivieren", role="Rolle, die den Trigger auslöst", language="de oder en")
    async def setup_newmember(self, ctx: commands.Context, enabled: bool, role: Optional[discord.Role] = None, language: str = "de"):
        """Setup für das New-Member-System (Mods/Admins)."""
        language = language.lower()
        if language not in LANGS:
            language = "de"
        await self.config.guild(ctx.guild).enabled.set(enabled)
        if role:
            await self.config.guild(ctx.guild).role_id.set(role.id)
        await self.config.guild(ctx.guild).language.set(language)
        await ctx.reply(_t(language, "cfg_saved", enabled=enabled, role=role.name if role else None, lang=language))

    @checks.mod_or_permissions(manage_guild=True)
    @commands.hybrid_command(name="setwgguild")
    @app_commands.describe(region="eu/us/kr/tw", realm="Realmname (z.B. Blackrock)", guildname="Gildenname exakt")
    async def setwgguild(self, ctx: commands.Context, region: str, realm: str, guildname: str):
        """Setzt Region/Realm/Gilde für den WoW-API-Abgleich (Mods/Admins)."""
        region = region.lower()
        if region not in ("eu", "us", "kr", "tw"):
            region = "eu"
        await self.config.guild(ctx.guild).wow_region.set(region)
        await self.config.guild(ctx.guild).wow_realm.set(realm)
        await self.config.guild(ctx.guild).wow_guild.set(guildname)
        lang = (await self.config.guild(ctx.guild).language())
        await ctx.reply(_t(lang, "guild_saved", region=region, realm=realm, guild=guildname))

    @checks.mod_or_permissions(manage_guild=True)
    @commands.hybrid_command(name="setwowapi")
    @app_commands.describe(region="eu/us/kr/tw", client_id="Battle.net Client ID", client_secret="Battle.net Client Secret", active="API-Check aktivieren/deaktivieren")
    async def setwowapi(self, ctx: commands.Context, region: str, client_id: str, client_secret: str, active: Optional[bool] = True):
        """Setzt Battle.net API-Credentials & aktiviert/ deaktiviert den Check (Mods/Admins)."""
        region = region.lower()
        if region not in ("eu", "us", "kr", "tw"):
            region = "eu"
        all_creds = await self.config.wow_api()
        all_creds.setdefault(region, {})
        all_creds[region]["client_id"] = client_id
        all_creds[region]["client_secret"] = client_secret
        await self.config.wow_api.set(all_creds)
        if active is not None:
            await self.config.guild(ctx.guild).wow_api_enabled.set(bool(active))
        lang = (await self.config.guild(ctx.guild).language())
        await ctx.reply(_t(lang, "api_saved", active=bool(active)))

    @commands.hybrid_command(name="getmemberchars")
    async def getmemberchars(self, ctx: commands.Context):
        """Listet alle gespeicherten Chars (per DM an dich)."""
        lang = (await self.config.guild(ctx.guild).language())
        data = await self.config.all_users()
        lines = []
        for user_id, chars in data.items():
            user = ctx.guild.get_member(int(user_id))
            if not user:
                continue
            main = chars.get("main")
            tw = chars.get("twinks", [])
            if not main and not tw:
                continue
            part = f"{user.display_name} => "
            if main:
                part += f"{main} (Main)"
                if tw:
                    part += ", " + ", ".join([f"{x} (Twink)" for x in tw])
            else:
                part += ", ".join([f"{x} (Twink)" for x in tw])
            lines.append(part)

        msg = "\n".join(lines) if lines else _t(lang, "no_chars")
        try:
            await ctx.author.send(f"**{ctx.guild.name}** —\n{msg}")
            await ctx.reply(_t(lang, "sent_dm"), ephemeral=True)
        except discord.Forbidden:
            await ctx.reply(_t(lang, "dm_failed"), ephemeral=True)

    @commands.hybrid_command(name="setmainchar")
    @app_commands.describe(charname="Name deines Hauptchars")
    async def setmainchar(self, ctx: commands.Context, *, charname: str):
        """Setzt deinen Hauptcharakter."""
        lang = (await self.config.guild(ctx.guild).language())
        # Optional check
        gconf = await self.config.guild(ctx.guild).all()
        checked = await self._check_wow_guild(ctx.guild, charname)
        if checked is False and gconf.get("wow_api_enabled", True):
            await ctx.reply(_t(lang, "ask_main_retry", guild=gconf.get("wow_guild") or ctx.guild.name), ephemeral=True)
            return
        await self.config.user(ctx.author).main.set(charname)
        await self._dump_all_members()
        await ctx.reply(_t(lang, "main_set", char=charname), ephemeral=True)

    @commands.hybrid_command(name="settwinkchar")
    @app_commands.describe(charname="Name des Twinks")
    async def settwinkchar(self, ctx: commands.Context, *, charname: str):
        """Füge einen Twink hinzu."""
        lang = (await self.config.guild(ctx.guild).language())
        twinks = await self.config.user(ctx.author).twinks()
        if charname not in twinks:
            # Optional check (soft: nur warnen? hier direkt zulassen)
            twinks.append(charname)
            await self.config.user(ctx.author).twinks.set(twinks)
            await self._dump_all_members()
            await ctx.reply(_t(lang, "twink_added", char=charname), ephemeral=True)
        else:
            await ctx.reply(_t(lang, "twink_exists"), ephemeral=True)

    @commands.hybrid_command(name="removetwink")
    async def removetwink(self, ctx: commands.Context):
        """Entferne einen Twink (mit Dropdown)."""
        lang = (await self.config.guild(ctx.guild).language())
        twinks = await self.config.user(ctx.author).twinks()
        if not twinks:
            await ctx.reply(_t(lang, "no_twink"), ephemeral=True)
            return
        view = RemoveTwinkView(self, ctx.author, lang)
        view.add_item(RemoveTwinkSelect(twinks, lang))
        await ctx.reply(content=" ", view=view, ephemeral=True)

    @commands.hybrid_command(name="removemainchar")
    async def removemainchar(self, ctx: commands.Context):
        """Entferne deinen Hauptchar (mit Dropdown)."""
        lang = (await self.config.guild(ctx.guild).language())
        main = await self.config.user(ctx.author).main()
        if not main:
            await ctx.reply(_t(lang, "no_main"), ephemeral=True)
            return
        view = RemoveMainView(self, ctx.author, lang)
        view.add_item(RemoveMainSelect(main, lang))
        await ctx.reply(content=" ", view=view, ephemeral=True)

    @checks.mod_or_permissions(manage_guild=True)
    @commands.hybrid_command(name="charrequest")
    @app_commands.describe(user="Discord User")
    async def charrequest(self, ctx: commands.Context, user: discord.Member):
        """Sendet die Charakter-Abfrage erneut an einen User (Mods/Admins)."""
        lang = (await self.config.guild(ctx.guild).language())
        gconf = await self.config.guild(ctx.guild).all()
        ok = await self._ask_for_main_via_dm(user, lang, gconf)
        if not ok:
            # trotzdem bestätigen, dass versucht wurde
            await ctx.reply(_t(lang, "dm_failed"), ephemeral=True)
        else:
            await ctx.reply(_t(lang, "charrequest_sent", user=user.display_name), ephemeral=True)


async def setup(bot: Red):
    await bot.add_cog(MemberCharSetup(bot))
