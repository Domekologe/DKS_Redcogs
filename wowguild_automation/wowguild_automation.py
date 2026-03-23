from typing import Any, Dict, Optional

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
        self.config.register_member(chars=[], ready_times={}, onboarding_language="de-DE")
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
        return await self.config.guild(guild).all()

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

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild_cfg = await self._guild_config(member.guild)
        if not guild_cfg.get("features", {}).get("onboarding", True):
            return

        new_role_id = guild_cfg.get("roles", {}).get("onboarding_new_role_id", 0)
        if new_role_id:
            new_role = member.guild.get_role(new_role_id)
            if new_role and new_role not in member.roles:
                await member.add_roles(new_role, reason="Onboarding started")

        manual_channel_id = guild_cfg.get("channels", {}).get("manual_review_channel_id", 0)
        manual_channel = (
            member.guild.get_channel(manual_channel_id) if manual_channel_id else None
        )
        if manual_channel and not isinstance(manual_channel, discord.TextChannel):
            manual_channel = None

        chosen_lang = await handle_new_member_onboarding(
            bot=self.bot,
            member=member,
            guild_config=guild_cfg,
            rank_sync=self.rank_sync,
            manual_channel=manual_channel,  # type: ignore[arg-type]
        )
        await self.config.member(member).onboarding_language.set(chosen_lang)

        complete_role_id = guild_cfg.get("roles", {}).get("onboarding_complete_role_id", 0)
        if complete_role_id:
            complete_role = member.guild.get_role(complete_role_id)
            if complete_role and complete_role not in member.roles:
                await member.add_roles(complete_role, reason="Onboarding completed")

        if new_role_id:
            new_role = member.guild.get_role(new_role_id)
            if new_role and new_role in member.roles:
                await member.remove_roles(new_role, reason="Onboarding completed")

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

        await self.config.guild(ctx.guild).language.set(language)
        await self.config.guild(ctx.guild).wow.set(
            {
                "region": region.lower().strip(),
                "version": version.lower().strip(),
                "realm": realm.strip(),
                "guild_name": guildname.strip(),
            }
        )
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
        return {
            "status": 0,
            "web_content": {
                "title": "WoW Guild Automation",
                "description": (
                    "Available pages: global `wowguild_master` (owner) and "
                    "guild `wowguild_automation` (server context)."
                ),
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
        user_id: int,
        method: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        _ = kwargs
        if user_id not in self.bot.owner_ids:
            return {"status": 1, "message": "Not allowed."}

        bot_setup = await self.config.bot_setup()
        if method.upper() == "POST":
            payload: Dict[str, Any] = {}
            if data:
                payload.update(dict(data.get("json", {})))
                payload.update(dict(data.get("form", {})))

            lang = str(payload.get("default_language", bot_setup.get("default_language", "de-DE"))).strip()
            if lang not in ("de-DE", "en-US"):
                lang = "de-DE"
            bot_setup["default_language"] = lang
            bot_setup["default_region"] = str(
                payload.get("default_region", bot_setup.get("default_region", "eu"))
            ).strip().lower()
            bot_setup["default_version"] = str(
                payload.get("default_version", bot_setup.get("default_version", "retail"))
            ).strip().lower()
            raw_enabled = payload.get("dashboard_enabled", bot_setup.get("dashboard_enabled", True))
            if isinstance(raw_enabled, str):
                bot_setup["dashboard_enabled"] = raw_enabled.lower() in ("1", "true", "yes", "on")
            else:
                bot_setup["dashboard_enabled"] = bool(raw_enabled)

            await self.config.bot_setup.set(bot_setup)
            return {
                "status": 0,
                "notifications": [{"message": "WoW master settings saved.", "category": "success"}],
            }

        return {
            "status": 0,
            "web_content": {
                "title": "WoW Guild Automation - Master Settings",
                "config": bot_setup,
                "payload_example": {
                    "default_language": "de-DE",
                    "default_region": "eu",
                    "default_version": "retail",
                    "dashboard_enabled": True,
                },
            },
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
        user_id: int,
        guild_id: int,
        method: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        _ = kwargs
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return {"status": 1, "message": "Guild not found."}
        member = guild.get_member(user_id)
        if user_id not in self.bot.owner_ids and (
            member is None or not (await self.bot.is_admin(member) or member.guild_permissions.manage_guild)
        ):
            return {"status": 1, "message": "Not allowed."}

        cfg = await self._guild_config(guild)
        if method.upper() == "POST":
            payload: Dict[str, Any] = {}
            if data:
                payload.update(dict(data.get("json", {})))
                payload.update(dict(data.get("form", {})))

            def to_int(value: Any, default: int = 0) -> int:
                try:
                    return int(value)
                except Exception:
                    return default

            language = str(payload.get("language", cfg.get("language", "de-DE"))).strip()
            if language not in ("de-DE", "en-US"):
                language = "de-DE"
            cfg["language"] = language

            wow = cfg.get("wow", {})
            wow["region"] = str(payload.get("region", wow.get("region", "eu"))).strip().lower()
            wow["version"] = str(payload.get("version", wow.get("version", "retail"))).strip().lower()
            wow["realm"] = str(payload.get("realm", wow.get("realm", ""))).strip()
            wow["guild_name"] = str(payload.get("guild_name", wow.get("guild_name", ""))).strip()
            cfg["wow"] = wow

            roles = cfg.get("roles", {})
            roles["guest_role_id"] = to_int(payload.get("guest_role_id", roles.get("guest_role_id", 0)))
            roles["member_role_id"] = to_int(payload.get("member_role_id", roles.get("member_role_id", 0)))
            roles["onboarding_new_role_id"] = to_int(
                payload.get("onboarding_new_role_id", roles.get("onboarding_new_role_id", 0))
            )
            roles["onboarding_complete_role_id"] = to_int(
                payload.get("onboarding_complete_role_id", roles.get("onboarding_complete_role_id", 0))
            )
            cfg["roles"] = roles

            channels = cfg.get("channels", {})
            channels["onboarding_channel_id"] = to_int(
                payload.get("onboarding_channel_id", channels.get("onboarding_channel_id", 0))
            )
            channels["manual_review_channel_id"] = to_int(
                payload.get("manual_review_channel_id", channels.get("manual_review_channel_id", 0))
            )
            channels["raid_guest_channel_id"] = to_int(
                payload.get("raid_guest_channel_id", channels.get("raid_guest_channel_id", 0))
            )
            cfg["channels"] = channels

            await self.config.guild(guild).set(cfg)
            await self._apply_onboarding_channel_permissions(guild)
            return {"status": 0, "notifications": [{"message": "WoW settings saved.", "category": "success"}]}

        return {
            "status": 0,
            "web_content": {
                "title": "WoW Guild Automation",
                "description": "GET to read settings, POST to update settings.",
                "config": cfg,
                "available_roles": [{"id": r.id, "name": r.name} for r in guild.roles],
                "available_channels": [{"id": c.id, "name": c.name} for c in guild.text_channels],
                "payload_example": {
                    "language": "de-DE",
                    "region": "eu",
                    "version": "retail",
                    "realm": "my-realm",
                    "guild_name": "my-guild",
                    "guest_role_id": 0,
                    "member_role_id": 0,
                    "onboarding_new_role_id": 0,
                    "onboarding_complete_role_id": 0,
                    "onboarding_channel_id": 0,
                    "manual_review_channel_id": 0,
                    "raid_guest_channel_id": 0,
                },
            },
        }


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WowGuildAutomation(bot))

