from typing import Any, Dict, Optional
import json
import traceback

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

try:
    # Late-bound by Dashboard when registering third-party pages.
    from dashboard.rpc.third_parties import dashboard_page as _dashboard_page  # type: ignore
except Exception:
    def _dashboard_page(*args: Any, **kwargs: Any):  # type: ignore
        def decorator(func: Any) -> Any:
            # Dashboard detects this marker and wraps it with its own decorator.
            func.__dashboard_decorator_params__ = (args, kwargs)
            return func
        return decorator

from .automation.new_user import handle_new_member_onboarding
from .functions.automations import RankSyncService
from .functions.blizzard import BlizzardService

I18N = {
    "de-DE": {
        "server_only": "Nur auf einem Server nutzbar.",
        "wow_help": "Nutze Unterbefehle wie `wow guildsettings` oder `wow chars`.",
        "readytimes_init": "Bereitschaftszeiten-Editor ist initialisiert. Der nächste Schritt wäre ein Modal/Button-UI pro Wochentag.",
        "settings_saved": "Guild-Setup gespeichert: `{region}/{version}/{realm}` - `{guild}`",
        "chars_none": "Keine Chars verlinkt.",
        "char_added": "Char `{char}` hinzugefügt.",
        "char_removed": "Char `{char}` entfernt.",
        "chars_invalid": "Ungültig. Benutze action: `list`, `add`, `remove`.",
        "rank_synced": "Rang erfolgreich synchronisiert: `{rank}`",
        "rank_failed": "Mainchar nicht gefunden oder API nicht konfiguriert.",
        "botsetup_saved": "Bot-Setup gespeichert.",
        "master_saved": "Master-Setup gespeichert.",
        "onboarding_setup_intro": "Onboarding-Setup gestartet. Antworte pro Schritt im Chat.",
        "onboarding_setup_mode": "Soll der Bot Channel/Rollen erstellen? Antworte mit `create` oder `existing`.",
        "onboarding_setup_done": "Onboarding-Setup gespeichert. Channel: {channel}, Rollen: new={new_role}, complete={complete_role}",
        "onboarding_setup_cancelled": "Setup abgebrochen oder ungültige Eingabe.",
        "prompt_new_role": "Sende die Rollen-ID fuer `onboarding-new` (oder `skip`).",
        "prompt_complete_role": "Sende die Rollen-ID fuer `onboarding-complete` (oder `skip`).",
        "prompt_channel": "Sende die Channel-ID fuer den Onboarding-Channel (oder `skip`).",
    },
    "en-US": {
        "server_only": "This command can only be used in a server.",
        "wow_help": "Use subcommands like `wow guildsettings` or `wow chars`.",
        "readytimes_init": "Ready-times editor initialized. Next step is a modal/button UI for each weekday.",
        "settings_saved": "Guild setup saved: `{region}/{version}/{realm}` - `{guild}`",
        "chars_none": "No characters linked.",
        "char_added": "Character `{char}` added.",
        "char_removed": "Character `{char}` removed.",
        "chars_invalid": "Invalid action. Use: `list`, `add`, `remove`.",
        "rank_synced": "Rank synchronized successfully: `{rank}`",
        "rank_failed": "Main character not found or API not configured.",
        "botsetup_saved": "Bot setup saved.",
        "master_saved": "Master setup saved.",
        "onboarding_setup_intro": "Onboarding setup started. Reply to each step in this channel.",
        "onboarding_setup_mode": "Should the bot create channel/roles? Reply with `create` or `existing`.",
        "onboarding_setup_done": "Onboarding setup saved. Channel: {channel}, Roles: new={new_role}, complete={complete_role}",
        "onboarding_setup_cancelled": "Setup cancelled or invalid input.",
        "prompt_new_role": "Send the role ID for `onboarding-new` (or `skip`).",
        "prompt_complete_role": "Send the role ID for `onboarding-complete` (or `skip`).",
        "prompt_channel": "Send the channel ID for the onboarding channel (or `skip`).",
    },
}


class WowGuildAutomation(commands.Cog):
    """WoW guild onboarding and role automation for Red."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=980231234, force_registration=True)
        self.config.register_global(
            bot_setup={
                "client_id": "",
                "client_secret": "",
                "owner_ids": [],
                "default_language": "de-DE",
                "default_region": "eu",
                "default_version": "retail",
                "dashboard_enabled": True,
            }
        )
        self.config.register_guild(
            language="de-DE",
            features={
                "onboarding": True,
                "auto_verify": True,
                "ready_times": True,
                "sync_rank": True,
            },
            wow={"region": "eu", "version": "retail", "realm": "", "guild_name": ""},
            wow_profiles={
                "retail": {"region": "eu", "version": "retail", "realm": "", "guild_name": ""}
            },
            onboarding={
                "welcome_text_de": "Willkommen beim Onboarding!",
                "welcome_text_en": "Welcome to onboarding!",
            },
            roles={
                "guest_role_id": 0,
                "member_role_id": 0,
                "onboarding_new_role_id": 0,
                "onboarding_complete_role_id": 0,
            },
            channels={
                "onboarding_channel_id": 0,
                "manual_review_channel_id": 0,
                "raid_guest_channel_id": 0,
            },
            rules={"rule_channel_id": 0, "rule_emoji": "✅"},
            templates={
                "manual_verification": "Manuelle Verifizierung nötig! User {username} hat sich gemeldet als Char {charname} und möchte Gildenrechte erhalten. Bitte bestätigen sie dies manuell."
            },
        )
        self.config.register_member(
            chars=[], ready_times={}, onboarding_language="de-DE", selected_game="retail"
        )
        self.blizzard = BlizzardService()
        self.rank_sync = RankSyncService(self.blizzard)
        self._dashboard_attached = False

    def _attach_to_dashboard(self, dashboard_cog: commands.Cog) -> bool:
        try:
            dashboard_cog.rpc.third_parties_handler.add_third_party(self, overwrite=True)  # type: ignore[attr-defined]
            return True
        except TypeError:
            # Backward compatibility for Dashboard versions without overwrite kwarg.
            try:
                dashboard_cog.rpc.third_parties_handler.add_third_party(self)  # type: ignore[attr-defined]
                return True
            except Exception:
                return False
        except Exception:
            return False

    async def cog_load(self) -> None:
        dashboard_cog = self.bot.get_cog("Dashboard")
        if dashboard_cog is not None:
            self._dashboard_attached = self._attach_to_dashboard(dashboard_cog)

    async def cog_unload(self) -> None:
        dashboard_cog = self.bot.get_cog("Dashboard")
        if dashboard_cog is not None:
            try:
                dashboard_cog.rpc.third_parties_handler.remove_third_party(self)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._dashboard_attached = False

    async def _guild_config(self, guild: discord.Guild) -> Dict[str, Any]:
        cfg = await self.config.guild(guild).all()
        wow_profiles = cfg.get("wow_profiles", {})
        if not wow_profiles:
            wow_single = cfg.get("wow", {})
            version_key = wow_single.get("version", "retail") or "retail"
            wow_profiles = {version_key: wow_single}
            cfg["wow_profiles"] = wow_profiles
            await self.config.guild(guild).set(cfg)
        return cfg

    async def _lang(self, ctx: commands.Context) -> str:
        if isinstance(ctx.author, discord.Member):
            member_lang = await self.config.member(ctx.author).onboarding_language()
            if member_lang in ("de-DE", "en-US"):
                return member_lang
        if ctx.guild:
            guild_lang = await self.config.guild(ctx.guild).language()
            if guild_lang in ("de-DE", "en-US"):
                return guild_lang
        return "de-DE"

    async def _t(self, ctx: commands.Context, key: str, **kwargs: str) -> str:
        lang = await self._lang(ctx)
        template = I18N.get(lang, I18N["de-DE"]).get(key, key)
        return template.format(**kwargs)

    async def _wait_text(self, ctx: commands.Context, timeout: int = 180) -> Optional[str]:
        def check(message: discord.Message) -> bool:
            return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=timeout)
        except Exception:
            return None
        return msg.content.strip()

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        if self._dashboard_attached:
            return
        self._dashboard_attached = self._attach_to_dashboard(dashboard_cog)

    @commands.Cog.listener()
    async def on_dashboard_cog_remove(self, dashboard_cog: commands.Cog) -> None:
        _ = dashboard_cog
        self._dashboard_attached = False

    async def _apply_onboarding_channel_permissions(self, guild: discord.Guild) -> None:
        cfg = await self._guild_config(guild)
        channel_id = cfg.get("channels", {}).get("onboarding_channel_id", 0)
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        roles = cfg.get("roles", {})
        new_role = guild.get_role(roles.get("onboarding_new_role_id", 0))
        complete_role = guild.get_role(roles.get("onboarding_complete_role_id", 0))

        await channel.set_permissions(guild.default_role, view_channel=False, send_messages=False)
        if new_role:
            await channel.set_permissions(new_role, view_channel=True, send_messages=True)
        if complete_role:
            await channel.set_permissions(complete_role, view_channel=False, send_messages=False)

    async def _run_onboarding_flow(self, member: discord.Member) -> None:
        guild_cfg = await self._guild_config(member.guild)
        if not guild_cfg.get("features", {}).get("onboarding", True):
            return

        new_role_id = guild_cfg.get("roles", {}).get("onboarding_new_role_id", 0)
        if new_role_id:
            new_role = member.guild.get_role(new_role_id)
            if new_role and new_role not in member.roles:
                await member.add_roles(new_role, reason="Onboarding started")

        manual_channel_id = guild_cfg.get("channels", {}).get("manual_review_channel_id", 0)
        manual_channel = member.guild.get_channel(manual_channel_id) if manual_channel_id else None
        if manual_channel and not isinstance(manual_channel, discord.TextChannel):
            manual_channel = None

        onboarding_result = await handle_new_member_onboarding(
            bot=self.bot,
            member=member,
            guild_config=guild_cfg,
            rank_sync=self.rank_sync,
            manual_channel=manual_channel,  # type: ignore[arg-type]
        )
        chosen_lang = onboarding_result
        selected_game = "retail"
        if "|" in onboarding_result:
            chosen_lang, selected_game = onboarding_result.split("|", 1)
        await self.config.member(member).onboarding_language.set(chosen_lang)
        await self.config.member(member).selected_game.set(selected_game)

        complete_role_id = guild_cfg.get("roles", {}).get("onboarding_complete_role_id", 0)
        if complete_role_id:
            complete_role = member.guild.get_role(complete_role_id)
            if complete_role and complete_role not in member.roles:
                await member.add_roles(complete_role, reason="Onboarding completed")

        if new_role_id:
            new_role = member.guild.get_role(new_role_id)
            if new_role and new_role in member.roles:
                await member.remove_roles(new_role, reason="Onboarding completed")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._run_onboarding_flow(member)

    @commands.hybrid_group(name="wow")
    @commands.guild_only()
    async def wow(self, ctx: commands.Context) -> None:
        """WoW guild automation commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send(await self._t(ctx, "wow_help"))

    @wow.command(name="readytimes-manage")
    async def wow_readytimes_manage(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(await self._t(ctx, "server_only"))
            return

        member_conf = self.config.member(ctx.author)
        current = await member_conf.ready_times()
        if not current:
            current = {
                "monday": [],
                "tuesday": [],
                "wednesday": [],
                "thursday": [],
                "friday": [],
                "saturday": [],
                "sunday": [],
            }
            await member_conf.ready_times.set(current)
        await ctx.send(await self._t(ctx, "readytimes_init"))

    @commands.hybrid_command(name="wow-readytimes-manage")
    @commands.guild_only()
    async def wow_readytimes_manage_direct(self, ctx: commands.Context) -> None:
        """Slash-style alias for readytimes."""
        await self.wow_readytimes_manage(ctx)

    @wow.command(name="guildsettings")
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_guildsettings(
        self,
        ctx: commands.Context,
        region: str,
        version: str,
        realm: str,
        guildname: str,
        language: str = "de-DE",
    ) -> None:
        if not ctx.guild:
            await ctx.send(await self._t(ctx, "server_only"))
            return

        cfg = await self._guild_config(ctx.guild)
        cfg["language"] = language if language in ("de-DE", "en-US") else "de-DE"
        version_key = version.lower().strip()
        profile = {
            "region": region.lower().strip(),
            "version": version_key,
            "realm": realm.strip(),
            "guild_name": guildname.strip(),
        }
        cfg.setdefault("wow_profiles", {})
        cfg["wow_profiles"][version_key] = profile
        cfg["wow"] = profile
        await self.config.guild(ctx.guild).set(cfg)
        await ctx.send(
            await self._t(
                ctx,
                "settings_saved",
                region=region,
                version=version,
                realm=realm,
                guild=guildname,
            )
        )

    @commands.hybrid_command(name="wow-guildsettings")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_guildsettings_direct(
        self,
        ctx: commands.Context,
        region: str,
        version: str,
        realm: str,
        guildname: str,
        language: str = "de-DE",
    ) -> None:
        """Slash-style alias for guild settings."""
        await self.wow_guildsettings(ctx, region, version, realm, guildname, language)

    @wow.command(name="chars")
    async def wow_chars(
        self,
        ctx: commands.Context,
        action: str,
        charname: Optional[str] = None,
    ) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(await self._t(ctx, "server_only"))
            return

        member_conf = self.config.member(ctx.author)
        chars = await member_conf.chars()

        action = action.lower().strip()
        if action == "list":
            msg = ", ".join(chars) if chars else await self._t(ctx, "chars_none")
            await ctx.send(msg)
        elif action == "add" and charname:
            if charname not in chars:
                chars.append(charname)
                await member_conf.chars.set(chars)
            await ctx.send(await self._t(ctx, "char_added", char=charname))
        elif action == "remove" and charname:
            if charname in chars:
                chars.remove(charname)
                await member_conf.chars.set(chars)
            await ctx.send(await self._t(ctx, "char_removed", char=charname))
        else:
            await ctx.send(await self._t(ctx, "chars_invalid"))

    @commands.hybrid_command(name="wow-chars")
    @commands.guild_only()
    async def wow_chars_direct(
        self,
        ctx: commands.Context,
        action: str,
        charname: Optional[str] = None,
    ) -> None:
        """Slash-style alias for character management."""
        await self.wow_chars(ctx, action, charname)

    @wow.command(name="syncrank")
    async def wow_syncrank(self, ctx: commands.Context, mainchar: str) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(await self._t(ctx, "server_only"))
            return

        cfg = await self._guild_config(ctx.guild)
        selected_game = await self.config.member(ctx.author).selected_game()
        wow_profiles = cfg.get("wow_profiles", {})
        if selected_game in wow_profiles:
            cfg = dict(cfg)
            cfg["wow"] = wow_profiles[selected_game]
        rank = await self.rank_sync.sync_member_rank(ctx.author, cfg, mainchar)
        if rank:
            await ctx.send(await self._t(ctx, "rank_synced", rank=rank))
            return
        await ctx.send(await self._t(ctx, "rank_failed"))

    @commands.hybrid_command(name="wow-syncrank")
    @commands.guild_only()
    async def wow_syncrank_direct(self, ctx: commands.Context, mainchar: str) -> None:
        """Slash-style alias for rank syncing."""
        await self.wow_syncrank(ctx, mainchar)

    @wow.command(name="botsetup")
    @commands.is_owner()
    async def wow_botsetup(
        self,
        ctx: commands.Context,
        client_id: str,
        client_secret: str,
    ) -> None:
        data = await self.config.bot_setup()
        owners = set(data.get("owner_ids", []))
        owners.add(ctx.author.id)
        data["owner_ids"] = list(owners)
        data["client_id"] = client_id
        data["client_secret"] = client_secret
        await self.config.bot_setup.set(data)
        self.blizzard.client_id = client_id
        self.blizzard.client_secret = client_secret
        await ctx.send(await self._t(ctx, "botsetup_saved"))

    @wow.command(name="mastersetup")
    @commands.is_owner()
    async def wow_mastersetup(
        self,
        ctx: commands.Context,
        default_language: str = "de-DE",
        default_region: str = "eu",
        default_version: str = "retail",
        dashboard_enabled: bool = True,
    ) -> None:
        data = await self.config.bot_setup()
        if default_language not in ("de-DE", "en-US"):
            default_language = "de-DE"
        data["default_language"] = default_language
        data["default_region"] = default_region.lower().strip()
        data["default_version"] = default_version.lower().strip()
        data["dashboard_enabled"] = bool(dashboard_enabled)
        await self.config.bot_setup.set(data)
        await ctx.send(await self._t(ctx, "master_saved"))

    @commands.hybrid_command(name="wow-botsetup")
    @commands.is_owner()
    async def wow_botsetup_direct(
        self,
        ctx: commands.Context,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Slash-style alias for bot owner setup."""
        await self.wow_botsetup(ctx, client_id, client_secret)

    @commands.hybrid_command(name="wow-mastersetup")
    @commands.is_owner()
    async def wow_mastersetup_direct(
        self,
        ctx: commands.Context,
        default_language: str = "de-DE",
        default_region: str = "eu",
        default_version: str = "retail",
        dashboard_enabled: bool = True,
    ) -> None:
        """Slash-style alias for master setup."""
        await self.wow_mastersetup(
            ctx,
            default_language=default_language,
            default_region=default_region,
            default_version=default_version,
            dashboard_enabled=dashboard_enabled,
        )

    @wow.command(name="onboarding-setup")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_onboarding_setup(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            await ctx.send(await self._t(ctx, "server_only"))
            return

        await ctx.send(await self._t(ctx, "onboarding_setup_intro"))
        await ctx.send(await self._t(ctx, "onboarding_setup_mode"))
        mode = await self._wait_text(ctx)
        if not mode:
            await ctx.send(await self._t(ctx, "onboarding_setup_cancelled"))
            return

        mode = mode.lower().strip()
        cfg = await self._guild_config(ctx.guild)
        roles = cfg.get("roles", {})
        channels = cfg.get("channels", {})

        new_role: Optional[discord.Role] = None
        complete_role: Optional[discord.Role] = None
        onboarding_channel: Optional[discord.TextChannel] = None

        if mode == "create":
            new_role = discord.utils.get(ctx.guild.roles, name="onboarding-new")
            if not new_role:
                new_role = await ctx.guild.create_role(
                    name="onboarding-new", reason="WoW onboarding setup"
                )
            complete_role = discord.utils.get(ctx.guild.roles, name="onboarding-complete")
            if not complete_role:
                complete_role = await ctx.guild.create_role(
                    name="onboarding-complete", reason="WoW onboarding setup"
                )
            onboarding_channel = discord.utils.get(
                ctx.guild.text_channels, name="onboarding-private"
            )
            if not onboarding_channel:
                onboarding_channel = await ctx.guild.create_text_channel(
                    name="onboarding-private", reason="WoW onboarding setup"
                )
        elif mode == "existing":
            await ctx.send(await self._t(ctx, "prompt_new_role"))
            new_role_raw = await self._wait_text(ctx)
            await ctx.send(await self._t(ctx, "prompt_complete_role"))
            complete_role_raw = await self._wait_text(ctx)
            await ctx.send(await self._t(ctx, "prompt_channel"))
            channel_raw = await self._wait_text(ctx)
            if not new_role_raw or not complete_role_raw or not channel_raw:
                await ctx.send(await self._t(ctx, "onboarding_setup_cancelled"))
                return

            if new_role_raw.lower() != "skip":
                try:
                    new_role = ctx.guild.get_role(int(new_role_raw))
                except ValueError:
                    new_role = None
            if complete_role_raw.lower() != "skip":
                try:
                    complete_role = ctx.guild.get_role(int(complete_role_raw))
                except ValueError:
                    complete_role = None
            if channel_raw.lower() != "skip":
                try:
                    channel_obj = ctx.guild.get_channel(int(channel_raw))
                    if isinstance(channel_obj, discord.TextChannel):
                        onboarding_channel = channel_obj
                except ValueError:
                    onboarding_channel = None
        else:
            await ctx.send(await self._t(ctx, "onboarding_setup_cancelled"))
            return

        roles["onboarding_new_role_id"] = new_role.id if new_role else 0
        roles["onboarding_complete_role_id"] = complete_role.id if complete_role else 0
        channels["onboarding_channel_id"] = onboarding_channel.id if onboarding_channel else 0
        cfg["roles"] = roles
        cfg["channels"] = channels
        await self.config.guild(ctx.guild).set(cfg)
        await self._apply_onboarding_channel_permissions(ctx.guild)

        await ctx.send(
            await self._t(
                ctx,
                "onboarding_setup_done",
                channel=onboarding_channel.mention if onboarding_channel else "none",
                new_role=new_role.mention if new_role else "none",
                complete_role=complete_role.mention if complete_role else "none",
            )
        )

    @commands.hybrid_command(name="wow-onboarding-setup")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_onboarding_setup_direct(self, ctx: commands.Context) -> None:
        """Slash-style alias for onboarding setup wizard."""
        await self.wow_onboarding_setup(ctx)

    @wow.command(name="simulate-join")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_simulate_join(self, ctx: commands.Context, member: discord.Member) -> None:
        await ctx.send(f"Simuliere Join-Onboarding fuer {member.mention}...")
        await self._run_onboarding_flow(member)
        await ctx.send("Simulation abgeschlossen.")

    @commands.hybrid_command(name="wow-simulate-join")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_simulate_join_direct(self, ctx: commands.Context, member: discord.Member) -> None:
        """Slash-style alias to simulate a member join onboarding."""
        await self.wow_simulate_join(ctx, member)

    @wow.command(name="dashboard-status")
    @commands.is_owner()
    async def wow_dashboard_status(self, ctx: commands.Context) -> None:
        dashboard_cog = self.bot.get_cog("Dashboard")
        if dashboard_cog is None:
            await ctx.send("Dashboard cog is not loaded.")
            return
        try:
            third_parties = dashboard_cog.rpc.third_parties_handler.third_parties  # type: ignore[attr-defined]
            names = sorted(third_parties.keys())
            disabled = await dashboard_cog.config.webserver.disabled_third_parties()  # type: ignore[attr-defined]
            wow_pages = []
            if "WowGuildAutomation" in third_parties:
                wow_pages = [
                    f"{page} (hidden={meta[1].get('hidden')})"
                    for page, meta in third_parties["WowGuildAutomation"].items()
                ]
            await ctx.send(
                "Dashboard loaded: yes"
                f" | attached: {self._dashboard_attached}"
                f" | third parties: {', '.join(names) if names else 'none'}"
                f" | disabled: {', '.join(disabled) if disabled else 'none'}"
                f" | wow pages: {', '.join(wow_pages) if wow_pages else 'none'}"
            )
        except Exception as e:
            await ctx.send(f"Dashboard status check failed: {e}")

    @_dashboard_page(name=None, description="WoW Guild Automation Dashboard")
    async def dashboard_home(self, **kwargs: Any) -> Dict[str, Any]:
        _ = kwargs
        source = """
<div style="padding: 12px;">
  <h2>WoW Guild Automation</h2>
  <p>Dashboard integration is active.</p>
  <p>Use contextual pages:</p>
  <ul>
    <li><b>wowguild_master</b> (bot owner/global settings)</li>
    <li><b>wowguild_automation</b> (guild/server settings)</li>
  </ul>
</div>
"""
        return {
            "status": 0,
            "web_content": {
                "source": source,
                "standalone": True,
            },
        }

    @_dashboard_page(
        name="wowguild_master",
        description="Global bot master settings for WoW Guild Automation.",
        methods=("GET", "POST"),
        context_ids=["user_id"],
        is_owner=True,
        hidden=False,
    )
    async def dashboard_wowguild_master(
        self,
        user_id: Optional[int] = None,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            _ = kwargs
            if user_id is None:
                return {
                    "status": 0,
                    "error_code": 400,
                    "message": "Missing context: user_id. Open this page from a logged-in owner context.",
                }
            if user_id not in self.bot.owner_ids:
                return {"status": 1, "message": "Not allowed."}

            bot_setup = await self.config.bot_setup()
            Form = kwargs.get("Form")
            if Form is not None:
                import wtforms

                class MasterForm(Form):
                    def __init__(_self) -> None:
                        super().__init__(prefix="master_")

                    client_id = wtforms.StringField("Blizzard Client ID")
                    client_secret = wtforms.StringField("Blizzard Client Secret")
                    default_language = wtforms.SelectField(
                        "Default Language",
                        choices=[("de-DE", "de-DE"), ("en-US", "en-US")],
                        validators=[wtforms.validators.DataRequired()],
                    )
                    default_region = wtforms.StringField(
                        "Default Region", validators=[wtforms.validators.DataRequired()]
                    )
                    default_version = wtforms.StringField(
                        "Default Version", validators=[wtforms.validators.DataRequired()]
                    )
                    dashboard_enabled = wtforms.BooleanField("Dashboard Enabled")
                    submit = wtforms.SubmitField("Save Master Settings")

                form = MasterForm()
                if method.upper() == "GET":
                    form.client_id.data = bot_setup.get("client_id", "")
                    form.client_secret.data = bot_setup.get("client_secret", "")
                    form.default_language.data = bot_setup.get("default_language", "de-DE")
                    form.default_region.data = bot_setup.get("default_region", "eu")
                    form.default_version.data = bot_setup.get("default_version", "retail")
                    form.dashboard_enabled.data = bool(bot_setup.get("dashboard_enabled", True))

                if form.validate_on_submit():
                    lang = str(form.default_language.data).strip()
                    if lang not in ("de-DE", "en-US"):
                        lang = "de-DE"
                    bot_setup["client_id"] = str(form.client_id.data or "").strip()
                    bot_setup["client_secret"] = str(form.client_secret.data or "").strip()
                    bot_setup["default_language"] = lang
                    bot_setup["default_region"] = str(form.default_region.data).strip().lower()
                    bot_setup["default_version"] = str(form.default_version.data).strip().lower()
                    bot_setup["dashboard_enabled"] = bool(form.dashboard_enabled.data)
                    await self.config.bot_setup.set(bot_setup)
                    self.blizzard.client_id = bot_setup["client_id"]
                    self.blizzard.client_secret = bot_setup["client_secret"]
                    return {
                        "status": 0,
                        "notifications": [{"message": "WoW master settings saved.", "category": "success"}],
                        "redirect_url": kwargs.get("request_url"),
                    }

                source = f"""
<style>
.wow-wrap {{
  background: linear-gradient(180deg, #15110c 0%, #1f160f 100%);
  border: 1px solid #8a6a3a;
  border-radius: 10px;
  padding: 14px;
  color: #f3e9d2;
}}
.wow-wrap h2 {{ color: #ffcc66; }}
.wow-wrap input, .wow-wrap select {{
  background: #2b1f14;
  color: #f5e7c8;
  border: 1px solid #7d5b2b;
  border-radius: 6px;
  padding: 6px;
  min-width: 360px;
}}
</style>
<div class="wow-wrap">
  <h2>WoW Master Settings</h2>
  <p>Global defaults and Blizzard credentials for all guild instances.</p>
  <form method="post">
    {form.hidden_tag()}
    <p><label>Default Language</label><br>{form.default_language()}</p>
    <p><label>Blizzard Client ID</label><br>{form.client_id()}</p>
    <p><label>Blizzard Client Secret</label><br>{form.client_secret()}</p>
    <p><label>Default Region</label><br>{form.default_region()}</p>
    <p><label>Default Version</label><br>{form.default_version()}</p>
    <p><label>{form.dashboard_enabled()} Dashboard Enabled</label></p>
    <p>{form.submit()}</p>
  </form>
</div>
"""
                return {"status": 0, "web_content": {"source": source, "standalone": True}}

            return {
                "status": 0,
                "web_content": {
                    "source": (
                        "<div style='padding:12px;'>"
                        "<h2>WoW Master Settings</h2>"
                        "<p>Use POST on this page endpoint to update values.</p>"
                        "<h3>Current Config</h3>"
                        f"<pre>{json.dumps(bot_setup, indent=2)}</pre>"
                        "<h3>Payload Example</h3>"
                        "<pre>{\n"
                        '  "default_language": "de-DE",\n'
                        '  "default_region": "eu",\n'
                        '  "default_version": "retail",\n'
                        '  "dashboard_enabled": true\n'
                        "}</pre>"
                        "</div>"
                    ),
                    "standalone": True,
                },
            }
        except Exception as e:
            return {
                "status": 0,
                "error_code": 500,
                "message": f"Master page failed: {e}",
                "error_message": traceback.format_exc(limit=2),
            }

    @_dashboard_page(
        name="wowguild_automation",
        description="Configure WoW Guild Automation for this server.",
        methods=("GET", "POST"),
        context_ids=["user_id", "guild_id"],
        hidden=False,
    )
    async def dashboard_wowguild_automation(
        self,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            _ = kwargs
            if user_id is None or guild_id is None:
                return {
                    "status": 0,
                    "error_code": 400,
                    "message": "Missing context: user_id/guild_id. Open this page from a server context.",
                }
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return {"status": 1, "message": "Guild not found."}
            member = guild.get_member(user_id)
            if user_id not in self.bot.owner_ids and (
                member is None or not (await self.bot.is_admin(member) or member.guild_permissions.manage_guild)
            ):
                return {"status": 1, "message": "Not allowed."}

            cfg = await self._guild_config(guild)
            Form = kwargs.get("Form")
            if Form is not None:
                import wtforms

                class GuildForm(Form):
                    def __init__(_self) -> None:
                        super().__init__(prefix="guild_")

                    language = wtforms.SelectField(
                        "Language", choices=[("de-DE", "de-DE"), ("en-US", "en-US")]
                    )
                    profile_key = wtforms.SelectField("WoW Profile")
                    region = wtforms.StringField("Profile Region")
                    version = wtforms.StringField("Profile Version")
                    realm = wtforms.StringField("Realm")
                    guild_name = wtforms.StringField("Guild Name")
                    welcome_text_de = wtforms.StringField("Onboarding Text DE")
                    welcome_text_en = wtforms.StringField("Onboarding Text EN")
                    guest_role_id = wtforms.SelectField("Guest Role")
                    member_role_id = wtforms.SelectField("Member Role")
                    onboarding_new_role_id = wtforms.SelectField("Onboarding New Role")
                    onboarding_complete_role_id = wtforms.SelectField("Onboarding Complete Role")
                    onboarding_channel_id = wtforms.SelectField("Onboarding Channel")
                    manual_review_channel_id = wtforms.SelectField("Manual Review Channel")
                    raid_guest_channel_id = wtforms.SelectField("Raid Guest Channel")
                    create_missing_resources = wtforms.BooleanField(
                        "Create missing roles/channels automatically"
                    )
                    target_category_id = wtforms.SelectField("Target Category for new channels")
                    guest_role_name = wtforms.StringField("Create Guest Role Name")
                    member_role_name = wtforms.StringField("Create Member Role Name")
                    onboarding_new_role_name = wtforms.StringField("Create Onboarding New Role Name")
                    onboarding_complete_role_name = wtforms.StringField("Create Onboarding Complete Role Name")
                    onboarding_channel_name = wtforms.StringField("Create Onboarding Channel Name")
                    manual_review_channel_name = wtforms.StringField("Create Manual Review Channel Name")
                    raid_guest_channel_name = wtforms.StringField("Create Raid Guest Channel Name")
                    submit = wtforms.SubmitField("Save Guild Settings")

                form = GuildForm()
                wow_profiles = cfg.get("wow_profiles", {})
                active_key = next(iter(wow_profiles.keys()), "retail")
                wow = wow_profiles.get(active_key, cfg.get("wow", {}))
                roles = cfg.get("roles", {})
                channels = cfg.get("channels", {})
                onboarding = cfg.get("onboarding", {})
                role_choices = [("0", "-- none --")] + [
                    (str(role.id), f"{role.name} ({role.id})")
                    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)
                ]
                channel_choices = [("0", "-- none --")] + [
                    (str(channel.id), f"#{channel.name} ({channel.id})") for channel in guild.text_channels
                ]
                category_choices = [("0", "-- no category --")] + [
                    (str(category.id), f"{category.name} ({category.id})") for category in guild.categories
                ]
                profile_choices = [(k, k) for k in sorted(wow_profiles.keys())] or [("retail", "retail")]
                form.profile_key.choices = profile_choices + [("__new__", "+ create new profile")]
                form.guest_role_id.choices = role_choices
                form.member_role_id.choices = role_choices
                form.onboarding_new_role_id.choices = role_choices
                form.onboarding_complete_role_id.choices = role_choices
                form.onboarding_channel_id.choices = channel_choices
                form.manual_review_channel_id.choices = channel_choices
                form.raid_guest_channel_id.choices = channel_choices
                form.target_category_id.choices = category_choices
                if method.upper() == "GET":
                    form.language.data = cfg.get("language", "de-DE")
                    form.profile_key.data = active_key
                    form.region.data = wow.get("region", "eu")
                    form.version.data = wow.get("version", "retail")
                    form.realm.data = wow.get("realm", "")
                    form.guild_name.data = wow.get("guild_name", "")
                    form.welcome_text_de.data = onboarding.get("welcome_text_de", "")
                    form.welcome_text_en.data = onboarding.get("welcome_text_en", "")
                    form.guest_role_id.data = str(roles.get("guest_role_id", 0))
                    form.member_role_id.data = str(roles.get("member_role_id", 0))
                    form.onboarding_new_role_id.data = str(roles.get("onboarding_new_role_id", 0))
                    form.onboarding_complete_role_id.data = str(roles.get("onboarding_complete_role_id", 0))
                    form.onboarding_channel_id.data = str(channels.get("onboarding_channel_id", 0))
                    form.manual_review_channel_id.data = str(channels.get("manual_review_channel_id", 0))
                    form.raid_guest_channel_id.data = str(channels.get("raid_guest_channel_id", 0))
                    form.create_missing_resources.data = False
                    form.target_category_id.data = "0"
                    form.guest_role_name.data = "guest"
                    form.member_role_name.data = "guild-member"
                    form.onboarding_new_role_name.data = "onboarding-new"
                    form.onboarding_complete_role_name.data = "onboarding-complete"
                    form.onboarding_channel_name.data = "onboarding-private"
                    form.manual_review_channel_name.data = "wow-manual-review"
                    form.raid_guest_channel_name.data = "wow-raid-guests"

                if form.validate_on_submit():
                    cfg["language"] = form.language.data if form.language.data in ("de-DE", "en-US") else "de-DE"
                    if form.profile_key.data == "__new__":
                        profile_key = str(form.version.data or "retail").strip().lower()
                    else:
                        profile_key = str(form.profile_key.data or form.version.data or "retail").strip().lower()
                    profile = {
                        "region": str(form.region.data or "eu").strip().lower(),
                        "version": str(form.version.data or profile_key or "retail").strip().lower(),
                        "realm": str(form.realm.data or "").strip(),
                        "guild_name": str(form.guild_name.data or "").strip(),
                    }
                    cfg.setdefault("wow_profiles", {})
                    cfg["wow_profiles"][profile_key] = profile
                    cfg["wow"] = profile
                    cfg["onboarding"] = {
                        "welcome_text_de": str(form.welcome_text_de.data or "").strip(),
                        "welcome_text_en": str(form.welcome_text_en.data or "").strip(),
                    }
                    cfg["roles"] = {
                        "guest_role_id": int(form.guest_role_id.data or 0),
                        "member_role_id": int(form.member_role_id.data or 0),
                        "onboarding_new_role_id": int(form.onboarding_new_role_id.data or 0),
                        "onboarding_complete_role_id": int(form.onboarding_complete_role_id.data or 0),
                    }
                    cfg["channels"] = {
                        "onboarding_channel_id": int(form.onboarding_channel_id.data or 0),
                        "manual_review_channel_id": int(form.manual_review_channel_id.data or 0),
                        "raid_guest_channel_id": int(form.raid_guest_channel_id.data or 0),
                    }
                    notifications = []
                    if form.create_missing_resources.data:
                        category = None
                        try:
                            category = guild.get_channel(int(form.target_category_id.data or 0))
                            if category and not isinstance(category, discord.CategoryChannel):
                                category = None
                        except Exception:
                            category = None

                        role_create_map = [
                            ("guest_role_id", form.guest_role_name.data or "guest"),
                            ("member_role_id", form.member_role_name.data or "guild-member"),
                            ("onboarding_new_role_id", form.onboarding_new_role_name.data or "onboarding-new"),
                            (
                                "onboarding_complete_role_id",
                                form.onboarding_complete_role_name.data or "onboarding-complete",
                            ),
                        ]
                        for key, role_name in role_create_map:
                            if cfg["roles"].get(key, 0):
                                continue
                            existing = discord.utils.get(guild.roles, name=role_name)
                            if existing is None:
                                existing = await guild.create_role(
                                    name=role_name, reason="WoW dashboard auto-create role"
                                )
                                notifications.append(
                                    {"message": f"Created role: {existing.name}", "category": "info"}
                                )
                            cfg["roles"][key] = existing.id

                        channel_create_map = [
                            ("onboarding_channel_id", form.onboarding_channel_name.data or "onboarding-private"),
                            ("manual_review_channel_id", form.manual_review_channel_name.data or "wow-manual-review"),
                            ("raid_guest_channel_id", form.raid_guest_channel_name.data or "wow-raid-guests"),
                        ]
                        for key, channel_name in channel_create_map:
                            if cfg["channels"].get(key, 0):
                                continue
                            existing_channel = discord.utils.get(guild.text_channels, name=channel_name)
                            if existing_channel is None:
                                existing_channel = await guild.create_text_channel(
                                    name=channel_name,
                                    category=category,
                                    reason="WoW dashboard auto-create channel",
                                )
                                notifications.append(
                                    {
                                        "message": f"Created channel: #{existing_channel.name}",
                                        "category": "info",
                                    }
                                )
                            cfg["channels"][key] = existing_channel.id

                    await self.config.guild(guild).set(cfg)
                    await self._apply_onboarding_channel_permissions(guild)
                    return {
                        "status": 0,
                        "notifications": notifications + [{"message": "WoW guild settings saved.", "category": "success"}],
                        "redirect_url": kwargs.get("request_url"),
                    }

                source = f"""
<style>
.wow-wrap {{
  background: linear-gradient(180deg, #16120d 0%, #20160f 100%);
  border: 1px solid #8a6a3a;
  border-radius: 10px;
  padding: 14px;
  color: #f3e9d2;
  box-shadow: 0 0 20px rgba(0,0,0,.35);
}}
.wow-wrap h2, .wow-wrap h3 {{ color: #ffcc66; margin: 4px 0 10px 0; }}
.wow-wrap label {{ color: #ffe7b0; font-weight: 600; }}
.wow-wrap input, .wow-wrap select {{
  background: #2b1f14;
  color: #f5e7c8;
  border: 1px solid #7d5b2b;
  border-radius: 6px;
  padding: 6px;
  min-width: 360px;
}}
.wow-wrap hr {{ border-color: #6f5129; opacity: .6; }}
</style>
<div class="wow-wrap">
  <h2>WoW Guild Settings</h2>
  <p>Settings for <b>{guild.name}</b> - For the Horde/Alliance dashboard mode.</p>
  <form method="post">
    {form.hidden_tag()}
    <h3>Profile</h3>
    <p><label>Language</label><br>{form.language()}</p>
    <p><label>WoW Profile</label><br>{form.profile_key()}</p>
    <p><small>Select existing profile or choose <b>+ create new profile</b> and set version.</small></p>
    <p><label>Profile Region</label><br>{form.region()}</p>
    <p><label>Profile Version</label><br>{form.version()}</p>
    <p><label>Realm</label><br>{form.realm()}</p>
    <p><label>Guild Name</label><br>{form.guild_name()}</p>
    <p><label>Onboarding Text DE</label><br>{form.welcome_text_de()}</p>
    <p><label>Onboarding Text EN</label><br>{form.welcome_text_en()}</p>
    <hr>
    <h3>Discord Mapping</h3>
    <p><label>Guest Role</label><br>{form.guest_role_id()}</p>
    <p><label>Member Role</label><br>{form.member_role_id()}</p>
    <p><label>Onboarding New Role</label><br>{form.onboarding_new_role_id()}</p>
    <p><label>Onboarding Complete Role</label><br>{form.onboarding_complete_role_id()}</p>
    <hr>
    <p><label>Onboarding Channel</label><br>{form.onboarding_channel_id()}</p>
    <p><label>Manual Review Channel</label><br>{form.manual_review_channel_id()}</p>
    <p><label>Raid Guest Channel</label><br>{form.raid_guest_channel_id()}</p>
    <hr>
    <h3>Auto Create (optional)</h3>
    <p><label>{form.create_missing_resources()} Create missing roles/channels automatically</label></p>
    <p><label>Target Category for new channels</label><br>{form.target_category_id()}</p>
    <p><label>Guest Role Name</label><br>{form.guest_role_name()}</p>
    <p><label>Member Role Name</label><br>{form.member_role_name()}</p>
    <p><label>Onboarding New Role Name</label><br>{form.onboarding_new_role_name()}</p>
    <p><label>Onboarding Complete Role Name</label><br>{form.onboarding_complete_role_name()}</p>
    <p><label>Onboarding Channel Name</label><br>{form.onboarding_channel_name()}</p>
    <p><label>Manual Review Channel Name</label><br>{form.manual_review_channel_name()}</p>
    <p><label>Raid Guest Channel Name</label><br>{form.raid_guest_channel_name()}</p>
    <p>{form.submit()}</p>
  </form>
</div>
"""
                return {"status": 0, "web_content": {"source": source, "standalone": True}}

            return {
                "status": 0,
                "web_content": {
                    "source": (
                        "<div style='padding:12px;'>"
                        "<h2>WoW Guild Settings</h2>"
                        "<p>Use POST on this page endpoint to update values.</p>"
                        "<h3>Current Config</h3>"
                        f"<pre>{json.dumps(cfg, indent=2)}</pre>"
                        "<h3>Payload Example</h3>"
                        "<pre>{\n"
                        '  "language": "de-DE",\n'
                        '  "region": "eu",\n'
                        '  "version": "retail",\n'
                        '  "realm": "my-realm",\n'
                        '  "guild_name": "my-guild",\n'
                        '  "guest_role_id": 0,\n'
                        '  "member_role_id": 0,\n'
                        '  "onboarding_new_role_id": 0,\n'
                        '  "onboarding_complete_role_id": 0,\n'
                        '  "onboarding_channel_id": 0,\n'
                        '  "manual_review_channel_id": 0,\n'
                        '  "raid_guest_channel_id": 0\n'
                        "}</pre>"
                        "</div>"
                    ),
                    "standalone": True,
                },
            }
        except Exception as e:
            return {
                "status": 0,
                "error_code": 500,
                "message": f"Guild page failed: {e}",
                "error_message": traceback.format_exc(limit=2),
            }


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WowGuildAutomation(bot))

