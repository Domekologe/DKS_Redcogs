from typing import Any, Dict, List, Literal, Optional

# Slash: Literal erzwingt Auswahllisten (Zuverlässiger als nur @app_commands.choices bei Hybrid-Subcommands).
WowCharsAction = Literal["list", "add", "remove"]
WowCharsSpiel = Literal["retail", "mop_classic"]
import html
import json
import traceback
import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red

try:
    # Late-bound by Dashboard when registering third-party pages.
    from dks_dashboard.rpc.third_parties import dashboard_page as _dashboard_page  # type: ignore
except Exception:
    try:
        from dashboard.rpc.third_parties import dashboard_page as _dashboard_page  # type: ignore
    except Exception:
        def _dashboard_page(*args: Any, **kwargs: Any):  # type: ignore
            def decorator(func: Any) -> Any:
                # Dashboard detects this marker and wraps it with its own decorator.
                func.__dashboard_decorator_params__ = (args, kwargs)
                return func
            return decorator

from .automation.new_user import handle_new_member_onboarding
from .character_helpers import (
    GAME_MOP,
    GAME_RETAIL,
    char_tuple_key,
    clear_main_for_game,
    ensure_main_for_game_if_empty,
    find_char_owner_guild_wide,
    format_char_line,
    format_mains_summary,
    format_rank_sync_summary,
    game_label,
    get_linked_list,
    get_main_characters,
    mains_from_member_data,
    merge_onboarding_character_into_linked,
    merge_rank_sync_game_state,
    normalize_linked_characters,
    profile_key_to_link_game,
    set_linked_list,
    set_rank_sync_lock,
    wow_profile_for_game,
)
from .officer_notifications import send_protected_rank_officer_notice
from .character_ui import (
    CharMainMenuView,
    LinkedRemovePageView,
    OfficerListMenuView,
    PANEL_INTRO,
    SlashWowAdminListView,
    SlashWowAdminMemberPickView,
    SlashWowAdminSyncAllConfirmView,
    officer_can_manage_characters,
)
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
        "rank_synced_multi": "Rang-Sync:\n{lines}",
        "rank_failed": "Mainchar nicht gefunden oder API nicht konfiguriert.",
        "rank_sync_locked": "Rang-Sync für **{game}** ist eingefroren — Discord-Rolle unverändert.",
        "rank_sync_no_profile": "Kein WoW-Profil für **{game}** auf diesem Server.",
        "rank_freeze_ok": "Rang-Sync für **{game}** ist eingefroren. Manuelle Rollen bleiben erhalten bis `wow rank-unfreeze`.",
        "rank_unfreeze_ok": "Rang-Sync für **{game}** wieder aktiv.",
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
        "rank_synced_multi": "Rank sync:\n{lines}",
        "rank_failed": "Main character not found or API not configured.",
        "rank_sync_locked": "Rank sync for **{game}** is frozen — Discord role unchanged.",
        "rank_sync_no_profile": "No WoW profile configured for **{game}** on this server.",
        "rank_freeze_ok": "Rank sync for **{game}** is frozen. Manual roles stay until `wow rank-unfreeze`.",
        "rank_unfreeze_ok": "Rank sync for **{game}** is active again.",
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

    wow_char_grp = app_commands.Group(
        name="wow-char",
        description="WoW-Charaktere mit der Gilde verknüpfen (Retail / MoP Classic)",
    )
    wow_char_officer_grp = app_commands.Group(
        name="wow-char-officer",
        description="Officer: Charakterlisten und Entfernen",
    )
    # Top-level Slash: /wow-chars list|add|remove — keine generische „action“-Option
    wow_chars_slash_grp = app_commands.Group(
        name="wow-chars",
        description="Gildenchars: Liste, hinzufügen oder entfernen (nur Gildenroster).",
    )

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
            active_profile_key="retail",
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
            rank_mapping={},
            rank_titles={},
            rank_mapping_by_profile={},
            rank_titles_by_profile={},
            protected_rank_titles_by_profile={},
            channels={
                "onboarding_channel_id": 0,
                "manual_review_channel_id": 0,
                "raid_guest_channel_id": 0,
                "officer_character_notify_channel_id": 0,
                "rank_protected_notify_channel_id": 0,
            },
            rules={"rule_channel_id": 0, "rule_emoji": "✅"},
            templates={
                "manual_verification": "Manuelle Verifizierung nötig! User {username} hat sich gemeldet als Char {charname} und möchte Gildenrechte erhalten. Bitte bestätigen sie dies manuell.",
                "duplicate_character_message": "Dieser Charakter ist bereits verknüpft oder ungültig. Wende dich an einen Offizier. ({detail})",
                "member_left_characters_notice": "Mitglied {user} hat den Server verlassen. Verknüpfte Chars: {chars}",
                "admin_removed_char_dm": "Ein Offizier hat folgende WoW-Chars von dir entfernt: {chars}\nGrund: {reason}",
                "protected_rank_sync_notice": (
                    "{member} — **{game}**, Main `{char}`: Ingame-Rang **{rank}** ist geschützt; "
                    "kein automatischer Discord-Rang-Sync."
                ),
            },
        )
        self.config.register_member(
            chars=[],
            linked_characters=[],
            main_character=None,
            # Nur echte Dict-Einträge persistieren — Red nested_update bricht bei None-Blättern ab.
            main_characters={},
            ready_times={},
            onboarding_language="de-DE",
            selected_game="retail",
            registration={},
            onboarding_session_id="",
            rank_sync_by_game={},
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

    def _get_dashboard_cog(self) -> Optional[commands.Cog]:
        return self.bot.get_cog("DKS-Dashboard") or self.bot.get_cog("Dashboard")

    async def cog_load(self) -> None:
        bot_setup = await self.config.bot_setup()
        self.blizzard.client_id = bot_setup.get("client_id", "")
        self.blizzard.client_secret = bot_setup.get("client_secret", "")
        dashboard_cog = self._get_dashboard_cog()
        if dashboard_cog is not None:
            self._dashboard_attached = self._attach_to_dashboard(dashboard_cog)

    async def cog_unload(self) -> None:
        dashboard_cog = self._get_dashboard_cog()
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

    async def _send_private_ack(self, ctx: commands.Context, message: str) -> None:
        interaction = getattr(ctx, "interaction", None)
        if interaction is not None:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=True)
                else:
                    await interaction.followup.send(message, ephemeral=True)
                return
            except Exception:
                pass
        try:
            await ctx.author.send(message)
        except Exception:
            await ctx.send(message)

    async def _try_add_characters_for_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        game_type: str,
        names: List[str],
    ) -> tuple:
        cfg = await self._guild_config(guild)
        templates = cfg.get("templates", {})
        dup_tpl = templates.get(
            "duplicate_character_message",
            "Dieser Charakter ist bereits verknüpft ({detail})",
        )
        prof = await wow_profile_for_game(cfg, game_type)
        if not prof or not prof.get("realm") or not prof.get("guild_name"):
            return (
                f"Profil für **{game_label(game_type)}** ist unvollständig (Realm/Gilde im Dashboard setzen).",
                False,
            )
        roster = await self.blizzard.roster_character_names(
            prof.get("region", "eu"),
            prof.get("version", game_type),
            prof.get("realm", ""),
            prof.get("guild_name", ""),
        )
        roster_l = {n.lower() for n in roster}
        linked = await get_linked_list(self.config.member(member))
        to_add: List[Dict[str, str]] = []
        for raw_name in names:
            name = (raw_name or "").strip()
            if not name:
                continue
            if name.lower() not in roster_l:
                return (
                    f"`{name}` ist im **{game_label(game_type)}**-Gildenroster nicht (oder API-Fehler).",
                    False,
                )
            key = char_tuple_key(name, game_type)
            owner = await find_char_owner_guild_wide(
                self.config, guild, name, game_type, exclude_user_id=member.id
            )
            if owner is not None:
                return (dup_tpl.format(detail=f"bereits mit <@{owner}> verknüpft"), False)
            if any(char_tuple_key(e["name"], e["game_type"]) == key for e in linked):
                return (dup_tpl.format(detail="bereits bei dir verknüpft"), False)
            if any(char_tuple_key(e["name"], e["game_type"]) == key for e in to_add):
                continue
            to_add.append({"name": name, "game_type": game_type})
        merged = linked + to_add
        await set_linked_list(self.config.member(member), merged)
        labels = ", ".join(f"{x['name']} ({game_label(x['game_type'])})" for x in to_add)
        return (f"Verknüpft: {labels}" if labels else "Nichts hinzugefügt.", True)

    async def _guild_has_sync_rank(self, guild: discord.Guild) -> bool:
        cfg = await self._guild_config(guild)
        return bool(cfg.get("features", {}).get("sync_rank", True))

    async def _sync_rank_for_main(
        self,
        member: discord.Member,
        guild: discord.Guild,
        profile_key: str,
        main_name: str,
    ):
        raw = await self.config.member(member).rank_sync_by_game()
        locked = False
        if isinstance(raw, dict):
            st = raw.get(profile_key)
            if isinstance(st, dict):
                locked = bool(st.get("locked"))
        cfg = await self._guild_config(guild)
        profiles = cfg.get("wow_profiles") or {}
        if profile_key not in profiles:
            return None, "no_profile", 0
        selected_cfg = dict(cfg)
        selected_cfg["wow"] = profiles.get(profile_key, {})
        rank_title, reason, role_id = await self.rank_sync.sync_member_rank(
            member,
            selected_cfg,
            main_name.strip(),
            profile_key=profile_key,
            locked=locked,
        )
        if reason == "protected" and rank_title:
            await merge_rank_sync_game_state(
                self.config.member(member),
                profile_key,
                last_title=str(rank_title),
            )
            await send_protected_rank_officer_notice(
                guild,
                cfg,
                member,
                profile_key,
                main_name.strip(),
                rank_title,
            )
        return rank_title, reason, role_id

    async def _schedule_rank_sync_after_main(
        self,
        guild: discord.Guild,
        member: discord.Member,
        profile_key: str,
        main_name: str,
    ) -> None:
        try:
            if not await self._guild_has_sync_rank(guild):
                return
            rank_title, reason, role_id = await self._sync_rank_for_main(
                member, guild, profile_key, main_name
            )
            if reason == "ok" and rank_title and role_id:
                await merge_rank_sync_game_state(
                    self.config.member(member),
                    profile_key,
                    last_title=str(rank_title),
                    last_role_id=int(role_id),
                )
        except Exception:
            pass

    async def _slash_admin_sync_report_for_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ) -> str:
        if not await self._guild_has_sync_rank(guild):
            return "Rang-Sync ist auf diesem Server deaktiviert (`features.sync_rank`)."
        cfg = await self._guild_config(guild)
        wow_profiles = cfg.get("wow_profiles") or {}
        main_map = await get_main_characters(self.config.member(member))
        conf = self.config.member(member)
        jobs: List[tuple[str, str]] = []
        for g in (GAME_RETAIL, GAME_MOP):
            if g not in wow_profiles:
                continue
            m = main_map.get(g)
            if m and str(m.get("name", "")).strip():
                jobs.append((g, str(m["name"]).strip()))
        if not jobs:
            return "Kein Main für ein konfiguriertes Profil bei diesem Mitglied."
        lines: List[str] = []
        for game, name in jobs:
            rank_title, reason, role_id = await self._sync_rank_for_main(member, guild, game, name)
            gl = game_label(game)
            if reason == "ok" and rank_title and role_id:
                await merge_rank_sync_game_state(
                    conf,
                    game,
                    last_title=str(rank_title),
                    last_role_id=int(role_id),
                )
                lines.append(f"• **{gl}:** `{rank_title}` synchronisiert.")
            elif reason == "locked":
                lines.append(f"• **{gl}:** eingefroren — keine Rollenänderung.")
            elif reason == "protected":
                lines.append(f"• **{gl}:** geschützter Rang (Hinweis ggf. im Offizierskanal).")
            elif reason == "no_profile":
                lines.append(f"• **{gl}:** kein Profil konfiguriert.")
            elif reason in ("not_found", "no_role"):
                lines.append(f"• **{gl}:** nicht im Roster / kein Rollen-Mapping.")
            elif reason == "no_perms":
                lines.append(f"• **{gl}:** Bot darf Rollen nicht setzen.")
            elif reason == "http":
                lines.append(f"• **{gl}:** Discord-API-Fehler.")
            else:
                lines.append(f"• **{gl}:** {reason}")
        return f"**{member.display_name}** — Rang-Sync:\n" + "\n".join(lines)

    async def _slash_admin_sync_all_members_report(self, guild: discord.Guild) -> str:
        if not await self._guild_has_sync_rank(guild):
            return "Rang-Sync ist deaktiviert."
        data = await self.config.all_members(guild)
        blocks: List[str] = []
        for uid_str, payload in data.items():
            try:
                uid = int(uid_str)
            except (TypeError, ValueError):
                continue
            mem = guild.get_member(uid)
            if mem is None:
                continue
            linked = normalize_linked_characters(payload.get("linked_characters") or payload.get("chars"))
            if not linked:
                continue
            main_map = mains_from_member_data(payload)
            has_main = any(
                main_map.get(g) and str((main_map.get(g) or {}).get("name", "")).strip()
                for g in (GAME_RETAIL, GAME_MOP)
            )
            if not has_main:
                continue
            block = await self._slash_admin_sync_report_for_member(guild, mem)
            if "Kein Main für ein konfiguriertes Profil" in block:
                continue
            blocks.append(block)
        if not blocks:
            return "Keine Mitglieder mit verknüpften Chars und gesetztem Main."
        out = "\n\n".join(blocks[:15])
        if len(blocks) > 15:
            out += f"\n\n… gekürzt: **{len(blocks) - 15}** weitere Mitglieder — erneut ausführen oder einzeln syncen."
        return out[:3900]

    async def _format_user_char_list_ephemeral(
        self,
        guild: discord.Guild,
        member: discord.Member,
        *,
        header_user: bool = False,
    ) -> str:
        linked = await get_linked_list(self.config.member(member))
        mains = await get_main_characters(self.config.member(member))
        rs_raw = await self.config.member(member).rank_sync_by_game()
        rank_line = format_rank_sync_summary(guild, rs_raw)
        head = f"**{member.display_name}** (`{member.id}`)\n" if header_user else ""
        if not linked:
            extra = format_mains_summary(mains)
            if rank_line:
                extra += f"\n**Letzter Rang-Sync:** {rank_line}"
            return head + "Keine Chars verknüpft.\n" + extra
        lines = [format_char_line(e, mains) for e in linked]
        block = format_mains_summary(mains)
        if rank_line:
            block += f"\n**Letzter Rang-Sync:** {rank_line}"
        return head + block + "\n\n" + "\n".join(lines)

    async def _officer_format_all_linked_chars(self, guild: discord.Guild) -> str:
        data = await self.config.all_members(guild)
        lines: List[str] = []
        for uid_str, payload in data.items():
            linked = normalize_linked_characters(
                payload.get("linked_characters") or payload.get("chars")
            )
            if not linked:
                continue
            try:
                uid = int(uid_str)
            except (TypeError, ValueError):
                continue
            mem = guild.get_member(uid)
            label = mem.mention if mem else f"<@{uid}>"
            mains = mains_from_member_data(payload)
            parts = [format_char_line(e, mains) for e in linked]
            rank_snip = format_rank_sync_summary(guild, payload.get("rank_sync_by_game"))
            suffix = f" | {rank_snip}" if rank_snip else ""
            lines.append(f"{label}: {', '.join(parts)}{suffix}")
        return "\n".join(lines) if lines else "Keine verknüpften Chars auf diesem Server."

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        linked = await get_linked_list(self.config.member(member))
        mains_before = await get_main_characters(self.config.member(member))
        main_str = ", ".join(
            f"{game_label(g)}: {m['name']}"
            for g, m in mains_before.items()
            if m and str(m.get("name", "")).strip()
        )
        had_chars = bool(linked)
        await self.config.member(member).linked_characters.clear()
        await self.config.member(member).chars.clear()
        await self.config.member(member).main_character.clear()
        await self.config.member(member).main_characters.clear()
        await self.config.member(member).rank_sync_by_game.clear()
        await self.config.member(member).selected_game.clear()
        await self.config.member(member).registration.clear()
        if not had_chars:
            return
        guild = member.guild
        cfg = await self._guild_config(guild)
        ch_id = int(cfg.get("channels", {}).get("officer_character_notify_channel_id", 0) or 0)
        channel = guild.get_channel(ch_id) if ch_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        tpl = cfg.get("templates", {}).get(
            "member_left_characters_notice",
            "{user} hat den Server verlassen. Chars: {chars}",
        )
        char_lines = []
        for e in linked:
            char_lines.append(f"{e['name']} ({game_label(e['game_type'])})")
        chars_str = ", ".join(char_lines)
        try:
            await channel.send(
                tpl.format(
                    user=f"{member} ({member.id})",
                    username=str(member),
                    chars=chars_str,
                    main=main_str,
                )
            )
        except discord.HTTPException:
            pass

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
            await channel.set_permissions(new_role, view_channel=True, send_messages=False)
        if complete_role:
            await channel.set_permissions(complete_role, view_channel=False, send_messages=False)

    async def _run_onboarding_flow(self, member: discord.Member, simulated: bool = False) -> None:
        guild_cfg = await self._guild_config(member.guild)
        if not guild_cfg.get("features", {}).get("onboarding", True):
            return
        session_id = f"{datetime.now(timezone.utc).timestamp()}:{member.guild.id}:{member.id}"
        await self.config.member(member).onboarding_session_id.set(session_id)

        new_role_id = guild_cfg.get("roles", {}).get("onboarding_new_role_id", 0)
        if new_role_id:
            new_role = member.guild.get_role(new_role_id)
            if new_role and new_role not in member.roles:
                await member.add_roles(new_role, reason="Onboarding started")

        manual_channel_id = guild_cfg.get("channels", {}).get("manual_review_channel_id", 0)
        manual_channel = member.guild.get_channel(manual_channel_id) if manual_channel_id else None
        if manual_channel and not isinstance(manual_channel, discord.TextChannel):
            manual_channel = None
        onboarding_channel_id = guild_cfg.get("channels", {}).get("onboarding_channel_id", 0)
        onboarding_channel = (
            member.guild.get_channel(onboarding_channel_id) if onboarding_channel_id else None
        )
        if onboarding_channel and not isinstance(onboarding_channel, discord.TextChannel):
            onboarding_channel = None

        onboarding_result = await handle_new_member_onboarding(
            bot=self.bot,
            member=member,
            guild_config=guild_cfg,
            rank_sync=self.rank_sync,
            manual_channel=manual_channel,  # type: ignore[arg-type]
            onboarding_channel=onboarding_channel,  # type: ignore[arg-type]
            member_config=self.config.member(member),
        )
        chosen_lang = onboarding_result.get("language", "de-DE")
        selected_game = onboarding_result.get("selected_game", "retail")
        registration = onboarding_result.get("registration", {})
        registration["registered_at"] = datetime.now(timezone.utc).isoformat()
        rules_confirmed = bool(registration.get("rules_confirmed", False))
        await self.config.member(member).onboarding_language.set(chosen_lang)
        await self.config.member(member).selected_game.set(selected_game)
        await self.config.member(member).registration.set(registration)

        char_from_onboarding = str(registration.get("char_name") or "").strip()
        if registration.get("type") == "member" and char_from_onboarding:
            link_game = profile_key_to_link_game(selected_game)
            merged_ok = await merge_onboarding_character_into_linked(
                self.config,
                member.guild,
                member,
                char_from_onboarding,
                selected_game,
            )
            if merged_ok:
                await ensure_main_for_game_if_empty(
                    self.config.member(member),
                    link_game,
                    char_from_onboarding,
                )

        complete_role_id = guild_cfg.get("roles", {}).get("onboarding_complete_role_id", 0)
        if complete_role_id and rules_confirmed:
            complete_role = member.guild.get_role(complete_role_id)
            if complete_role and complete_role not in member.roles:
                await member.add_roles(complete_role, reason="Onboarding completed")

        if new_role_id and rules_confirmed:
            new_role = member.guild.get_role(new_role_id)
            if new_role and new_role in member.roles:
                await member.remove_roles(new_role, reason="Onboarding completed")

        if not rules_confirmed and not simulated:
            asyncio.create_task(self._send_rules_reminder_later(member, session_id))

    async def _send_rules_reminder_later(
        self, member: discord.Member, session_id: str, delay_seconds: int = 1800
    ) -> None:
        await asyncio.sleep(delay_seconds)
        # Only remind for the same fresh onboarding session.
        current_session = await self.config.member(member).onboarding_session_id()
        if current_session != session_id:
            return
        registration = await self.config.member(member).registration()
        if registration.get("rules_confirmed", False):
            return
        try:
            dm = await member.create_dm()
            await dm.send(
                "Erinnerung: Bitte bestaetige noch die Serverregeln, damit dein Onboarding abgeschlossen wird."
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._run_onboarding_flow(member, simulated=False)

    @commands.hybrid_group(
        name="wow",
        description="WoW-Gilde: Onboarding, Charaktere, Ränge und Server-Einstellungen.",
    )
    @commands.guild_only()
    async def wow(self, ctx: commands.Context) -> None:
        """WoW guild automation commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send(await self._t(ctx, "wow_help"))

    @wow.command(
        name="readytimes-manage",
        description="Bereitschaftszeiten ansehen (Editor folgt).",
    )
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

    @commands.hybrid_command(
        name="wow-readytimes-manage",
        description="Bereitschaftszeiten ansehen (Editor folgt).",
    )
    @commands.guild_only()
    async def wow_readytimes_manage_direct(self, ctx: commands.Context) -> None:
        """Bereitschaftszeiten ansehen (Editor folgt)."""
        await self.wow_readytimes_manage(ctx)

    @wow.command(
        name="guildsettings",
        description="Gilden-API: Region, Spielversion, Realm und Gildenname setzen.",
    )
    @commands.guild_only()
    @app_commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(
        region="Blizzard-Region, z. B. eu oder us",
        version="Profil-Version, z. B. retail oder mop_classic",
        realm="Realm-Slug, z. B. tarren-mill",
        guildname="Gildenname (exakt wie in WoW)",
        language="Bot-Sprache für diesen Server: de-DE oder en-US",
    )
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

    @commands.hybrid_command(
        name="wow-guildsettings",
        description="Gilden-API: Region, Spielversion, Realm und Gildenname setzen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(
        region="Blizzard-Region, z. B. eu oder us",
        version="Profil-Version, z. B. retail oder mop_classic",
        realm="Realm-Slug, z. B. tarren-mill",
        guildname="Gildenname (exakt wie in WoW)",
        language="Bot-Sprache für diesen Server: de-DE oder en-US",
    )
    async def wow_guildsettings_direct(
        self,
        ctx: commands.Context,
        region: str,
        version: str,
        realm: str,
        guildname: str,
        language: str = "de-DE",
    ) -> None:
        """Gilden-API: Region, Spielversion, Realm und Gildenname setzen."""
        await self.wow_guildsettings(ctx, region, version, realm, guildname, language)

    async def _wow_chars_execute(
        self,
        guild: discord.Guild,
        member: discord.Member,
        action: str,
        charname: Optional[str] = None,
        spiel: Optional[str] = None,
        *,
        chars_none_msg: str,
        chars_invalid_msg: str,
    ) -> str:
        """Gibt die Nutzer-Nachricht zurück (für Prefix und Slash)."""
        member_conf = self.config.member(member)
        linked = await get_linked_list(member_conf)
        mains = await get_main_characters(member_conf)

        action = (action or "").lower().strip()
        if action == "list":
            if not linked:
                return chars_none_msg
            return "\n".join(format_char_line(e, mains) for e in linked)
        if action == "add":
            if not charname or not str(charname).strip():
                return "Bitte einen Charakternamen angeben (Prefix: `wow chars add Meinchar retail`)."
            game = (spiel or GAME_RETAIL).lower()
            if game not in (GAME_RETAIL, GAME_MOP):
                game = GAME_RETAIL
            msg, _ok = await self._try_add_characters_for_member(
                guild, member, game, [str(charname).strip()]
            )
            return msg
        if action == "remove":
            if not charname or not str(charname).strip():
                return "Bitte einen Charakternamen angeben (optional: Spielversion)."
            raw_name = str(charname).strip()
            matches = [e for e in linked if e["name"].lower() == raw_name.lower()]
            if not matches:
                return chars_invalid_msg
            if len(matches) > 1 and not spiel:
                return (
                    "Dieser Name ist in **Retail** und **MoP** verknüpft — bitte `spiel` wählen (Slash) oder "
                    f"`wow chars remove {raw_name} retail` / `mop_classic` nutzen."
                )
            if spiel:
                spiel_l = str(spiel).lower()
                matches = [e for e in matches if e["game_type"].lower() == spiel_l]
            if len(matches) != 1:
                return chars_invalid_msg
            victim = matches[0]
            rkey = (victim["name"].lower(), victim["game_type"].lower())
            new_list = [
                e for e in linked if (e["name"].lower(), e["game_type"].lower()) != rkey
            ]
            await set_linked_list(member_conf, new_list)
            cur = mains.get(victim["game_type"])
            if cur and char_tuple_key(cur["name"], victim["game_type"]) == char_tuple_key(
                victim["name"], victim["game_type"]
            ):
                await clear_main_for_game(member_conf, victim["game_type"])
            return await self._t_from_guild(guild, member, "char_removed", char=victim["name"])
        return chars_invalid_msg

    async def _t_from_guild(
        self, guild: discord.Guild, member: discord.Member, key: str, **kwargs: Any
    ) -> str:
        """Resolve I18N wie _t, ohne Context."""
        member_lang = await self.config.member(member).onboarding_language()
        if member_lang in ("de-DE", "en-US"):
            lang = member_lang
        else:
            guild_lang = await self.config.guild(guild).language()
            lang = guild_lang if guild_lang in ("de-DE", "en-US") else "de-DE"
        tpl = I18N.get(lang, I18N["de-DE"]).get(key, key)
        try:
            return tpl.format(**kwargs)
        except Exception:
            return tpl

    @wow.command(
        name="chars",
        description="Gildenchars verknüpfen: Liste, hinzufügen oder entfernen (Roster).",
    )
    @commands.guild_only()
    @app_commands.guild_only()
    @app_commands.describe(
        action="Liste anzeigen, Char hinzufügen oder Char entfernen",
        charname="Name des Charakters (nur bei Hinzufügen/Entfernen)",
        spiel="Retail oder MoP — bei Entfernen nötig, wenn Name in beiden Spielen existiert",
    )
    async def wow_chars(
        self,
        ctx: commands.Context,
        action: WowCharsAction,
        charname: Optional[str] = None,
        spiel: Optional[WowCharsSpiel] = None,
    ) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(await self._t(ctx, "server_only"))
            return

        text = await self._wow_chars_execute(
            ctx.guild,
            ctx.author,
            action,
            charname,
            spiel,
            chars_none_msg=await self._t(ctx, "chars_none"),
            chars_invalid_msg=await self._t(ctx, "chars_invalid"),
        )
        await self._send_private_ack(ctx, text)

    @wow_chars_slash_grp.command(name="list", description="Deine verknüpften Gildenchars anzeigen")
    @app_commands.guild_only()
    async def slash_wow_chars_list(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        text = await self._wow_chars_execute(
            interaction.guild,
            interaction.user,
            "list",
            None,
            None,
            chars_none_msg=await self._t_from_guild(
                interaction.guild, interaction.user, "chars_none"
            ),
            chars_invalid_msg=await self._t_from_guild(
                interaction.guild, interaction.user, "chars_invalid"
            ),
        )
        await interaction.response.send_message(text, ephemeral=True)

    @wow_chars_slash_grp.command(
        name="add",
        description="Einen Char vom Gildenroster mit deinem Account verknüpfen",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        charname="Charaktername (wie im Gildenroster)",
        spiel="Retail oder MoP Classic (optional, Standard: Retail)",
    )
    async def slash_wow_chars_add(
        self,
        interaction: discord.Interaction,
        charname: str,
        spiel: Optional[WowCharsSpiel] = None,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        text = await self._wow_chars_execute(
            interaction.guild,
            interaction.user,
            "add",
            charname,
            spiel,
            chars_none_msg=await self._t_from_guild(
                interaction.guild, interaction.user, "chars_none"
            ),
            chars_invalid_msg=await self._t_from_guild(
                interaction.guild, interaction.user, "chars_invalid"
            ),
        )
        await interaction.response.send_message(text, ephemeral=True)

    @wow_chars_slash_grp.command(
        name="remove",
        description="Einen verknüpften Char von deinem Account entfernen",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        charname="Charaktername",
        spiel="Bei gleichem Namen in Retail und MoP: Version angeben",
    )
    async def slash_wow_chars_remove(
        self,
        interaction: discord.Interaction,
        charname: str,
        spiel: Optional[WowCharsSpiel] = None,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        text = await self._wow_chars_execute(
            interaction.guild,
            interaction.user,
            "remove",
            charname,
            spiel,
            chars_none_msg=await self._t_from_guild(
                interaction.guild, interaction.user, "chars_none"
            ),
            chars_invalid_msg=await self._t_from_guild(
                interaction.guild, interaction.user, "chars_invalid"
            ),
        )
        await interaction.response.send_message(text, ephemeral=True)

    @wow.command(
        name="syncrank",
        description="WoW-Gildenrang mit der passenden Discord-Rolle abgleichen.",
    )
    @commands.guild_only()
    @app_commands.guild_only()
    @app_commands.describe(
        mainchar="Optional: Charaktername; leer = alle Mains (pro konfiguriertem Profil)",
    )
    async def wow_syncrank(self, ctx: commands.Context, mainchar: Optional[str] = None) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(await self._t(ctx, "server_only"))
            return

        if not await self._guild_has_sync_rank(ctx.guild):
            await self._send_private_ack(
                ctx,
                "Rang-Sync ist auf diesem Server deaktiviert (`features.sync_rank`).",
            )
            return

        cfg = await self._guild_config(ctx.guild)
        wow_profiles = cfg.get("wow_profiles") or {}
        member_conf = self.config.member(ctx.author)

        async def _run_one(game: str, char_name: str):
            rank_title, reason, role_id = await self._sync_rank_for_main(
                ctx.author, ctx.guild, game, char_name
            )
            gl = game_label(game)
            if reason == "ok" and rank_title and role_id:
                await merge_rank_sync_game_state(
                    member_conf,
                    game,
                    last_title=str(rank_title),
                    last_role_id=int(role_id),
                )
                return f"• **{gl}:** `{rank_title}` synchronisiert.", rank_title
            if reason == "locked":
                return f"• **{gl}:** eingefroren — keine Rollenänderung.", None
            if reason == "protected":
                return (
                    f"• **{gl}:** Rang `{rank_title}` ist geschützt — kein Auto-Sync; Offiziere wurden benachrichtigt.",
                    None,
                )
            if reason == "no_profile":
                return f"• **{gl}:** kein Profil konfiguriert.", None
            if reason in ("not_found", "no_role"):
                return f"• **{gl}:** Char nicht im Roster oder kein Rollen-Mapping.", None
            if reason == "no_perms":
                return f"• **{gl}:** Bot darf Rollen nicht setzen.", None
            if reason == "http":
                return f"• **{gl}:** Discord-API-Fehler.", None
            return f"• **{gl}:** fehlgeschlagen ({reason}).", None

        if mainchar and mainchar.strip():
            mainchar = mainchar.strip()
            linked = await get_linked_list(member_conf)
            name_matches = [e for e in linked if e["name"].lower() == mainchar.lower()]
            if not name_matches:
                await self._send_private_ack(
                    ctx,
                    f"`{mainchar}` ist bei dir nicht verknüpft — zuerst Char hinzufügen.",
                )
                return
            if len(name_matches) == 1:
                game = name_matches[0]["game_type"]
                mainchar = name_matches[0]["name"]
            else:
                game = await member_conf.selected_game() or GAME_RETAIL
                pick = [e for e in name_matches if e["game_type"] == game]
                if len(pick) != 1:
                    await self._send_private_ack(
                        ctx,
                        "Dieser Name existiert in **Retail** und **MoP** — bitte Main setzen oder "
                        "Spiel im Panel wählen (`/wow-chars-panel`).",
                    )
                    return
                mainchar = pick[0]["name"]
                game = pick[0]["game_type"]
            line, synced_rank = await _run_one(game, mainchar)
            if synced_rank:
                await self._send_private_ack(
                    ctx,
                    await self._t(ctx, "rank_synced", rank=synced_rank),
                )
            else:
                await self._send_private_ack(ctx, line)
            return

        main_map = await get_main_characters(member_conf)
        jobs: List[tuple[str, str]] = []
        for g in (GAME_RETAIL, GAME_MOP):
            if g not in wow_profiles:
                continue
            m = main_map.get(g)
            if m and str(m.get("name", "")).strip():
                jobs.append((g, str(m["name"]).strip()))
        if not jobs:
            await self._send_private_ack(
                ctx,
                "Kein Main für ein konfiguriertes Profil gesetzt. Nutze `/wow-chars-panel` "
                "oder `wow syncrank <Charname>`.",
            )
            return
        out_lines: List[str] = []
        for g, n in jobs:
            line, _ = await _run_one(g, n)
            out_lines.append(line)
        await self._send_private_ack(
            ctx,
            await self._t(ctx, "rank_synced_multi", lines="\n".join(out_lines)),
        )

    @commands.hybrid_command(
        name="wow-syncrank",
        description="WoW-Gildenrang mit der passenden Discord-Rolle abgleichen.",
    )
    @commands.guild_only()
    @app_commands.describe(
        mainchar="Optional: Charaktername; leer = alle Mains (pro konfiguriertem Profil)",
    )
    async def wow_syncrank_direct(self, ctx: commands.Context, mainchar: Optional[str] = None) -> None:
        """WoW-Gildenrang mit der passenden Discord-Rolle abgleichen."""
        await self.wow_syncrank(ctx, mainchar)

    @wow.command(
        name="rank-freeze",
        description="Rang-Sync für ein Spiel anhalten — manuelle Discord-Rolle wird nicht überschrieben.",
    )
    @commands.guild_only()
    @app_commands.guild_only()
    @app_commands.describe(spiel="Retail oder MoP Classic")
    async def wow_rank_freeze(self, ctx: commands.Context, spiel: WowCharsSpiel) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(await self._t(ctx, "server_only"))
            return
        await set_rank_sync_lock(self.config.member(ctx.author), spiel, True)
        await self._send_private_ack(
            ctx,
            await self._t(ctx, "rank_freeze_ok", game=game_label(spiel)),
        )

    @commands.hybrid_command(
        name="wow-rank-freeze",
        description="Rang-Sync für ein Spiel anhalten (manuelle Rolle bleibt).",
    )
    @commands.guild_only()
    @app_commands.describe(spiel="Retail oder MoP Classic")
    async def wow_rank_freeze_direct(self, ctx: commands.Context, spiel: WowCharsSpiel) -> None:
        await self.wow_rank_freeze(ctx, spiel)

    @wow.command(
        name="rank-unfreeze",
        description="Rang-Sync für ein Spiel wieder aktivieren.",
    )
    @commands.guild_only()
    @app_commands.guild_only()
    @app_commands.describe(spiel="Retail oder MoP Classic")
    async def wow_rank_unfreeze(self, ctx: commands.Context, spiel: WowCharsSpiel) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(await self._t(ctx, "server_only"))
            return
        await set_rank_sync_lock(self.config.member(ctx.author), spiel, False)
        await self._send_private_ack(
            ctx,
            await self._t(ctx, "rank_unfreeze_ok", game=game_label(spiel)),
        )

    @commands.hybrid_command(
        name="wow-rank-unfreeze",
        description="Rang-Sync für ein Spiel wieder aktivieren.",
    )
    @commands.guild_only()
    @app_commands.describe(spiel="Retail oder MoP Classic")
    async def wow_rank_unfreeze_direct(self, ctx: commands.Context, spiel: WowCharsSpiel) -> None:
        await self.wow_rank_unfreeze(ctx, spiel)

    @wow.command(
        name="setrankmap",
        description="Einen WoW-Gildenrang (Titel) einer Discord-Rolle zuordnen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(
        rank_name="Rangbezeichnung wie im Mapping (z. B. aus wow listrankmap)",
        role="Discord-Rolle für diesen Rang",
    )
    async def wow_setrankmap(self, ctx: commands.Context, rank_name: str, role: discord.Role) -> None:
        if not ctx.guild:
            await ctx.send(await self._t(ctx, "server_only"))
            return
        cfg = await self._guild_config(ctx.guild)
        rank_mapping = cfg.get("rank_mapping", {})
        rank_mapping[rank_name.strip()] = role.id
        cfg["rank_mapping"] = rank_mapping
        await self.config.guild(ctx.guild).set(cfg)
        await ctx.send(f"Mapping gesetzt: `{rank_name}` -> {role.mention}")

    @commands.hybrid_command(
        name="wow-setrankmap",
        description="Einen WoW-Gildenrang (Titel) einer Discord-Rolle zuordnen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(
        rank_name="Rangbezeichnung wie im Mapping (z. B. aus wow listrankmap)",
        role="Discord-Rolle für diesen Rang",
    )
    async def wow_setrankmap_direct(
        self, ctx: commands.Context, rank_name: str, role: discord.Role
    ) -> None:
        """Einen WoW-Gildenrang (Titel) einer Discord-Rolle zuordnen."""
        await self.wow_setrankmap(ctx, rank_name, role)

    @wow.command(
        name="setranktitle",
        description="Anzeigetitel für einen Gildenrang-Index (0–9) setzen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(
        rank_index="Gildenrang-Index von 0 bis 9",
        title="Freier Titeltext für diesen Index",
    )
    async def wow_setranktitle(self, ctx: commands.Context, rank_index: int, title: str) -> None:
        if not ctx.guild:
            await ctx.send(await self._t(ctx, "server_only"))
            return
        cfg = await self._guild_config(ctx.guild)
        rank_titles = cfg.get("rank_titles", {})
        rank_titles[str(rank_index)] = title.strip()
        cfg["rank_titles"] = rank_titles
        await self.config.guild(ctx.guild).set(cfg)
        await ctx.send(f"Rangtitel gesetzt: Index `{rank_index}` -> `{title}`")

    @commands.hybrid_command(
        name="wow-setranktitle",
        description="Anzeigetitel für einen Gildenrang-Index (0–9) setzen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(
        rank_index="Gildenrang-Index von 0 bis 9",
        title="Freier Titeltext für diesen Index",
    )
    async def wow_setranktitle_direct(
        self, ctx: commands.Context, rank_index: int, title: str
    ) -> None:
        """Anzeigetitel für einen Gildenrang-Index (0–9) setzen."""
        await self.wow_setranktitle(ctx, rank_index, title)

    @wow.command(
        name="listrankmap",
        description="Aktives WoW-Profil: Rangtitel und Discord-Rollen-Mapping anzeigen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_listrankmap(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            await ctx.send(await self._t(ctx, "server_only"))
            return
        cfg = await self._guild_config(ctx.guild)
        active = cfg.get("active_profile_key", "retail")
        rank_titles_by_profile = cfg.get("rank_titles_by_profile", {})
        rank_mapping_by_profile = cfg.get("rank_mapping_by_profile", {})
        rank_titles = rank_titles_by_profile.get(active, cfg.get("rank_titles", {}))
        rank_mapping = rank_mapping_by_profile.get(active, cfg.get("rank_mapping", {}))
        lines = [f"Active profile: `{active}`", "Rank Titles:"]
        if rank_titles:
            for idx, title in sorted(rank_titles.items(), key=lambda kv: int(kv[0])):
                lines.append(f"- `{idx}` -> `{title}`")
        else:
            lines.append("- none")
        lines.append("\nRank Mapping:")
        if rank_mapping:
            for rank_name, role_id in rank_mapping.items():
                role = ctx.guild.get_role(int(role_id))
                role_label = role.mention if role else f"`{role_id}`"
                lines.append(f"- `{rank_name}` -> {role_label}")
        else:
            lines.append("- none")
        await ctx.send("\n".join(lines))

    @commands.hybrid_command(
        name="wow-listrankmap",
        description="Aktives WoW-Profil: Rangtitel und Discord-Rollen-Mapping anzeigen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_listrankmap_direct(self, ctx: commands.Context) -> None:
        """Aktives WoW-Profil: Rangtitel und Discord-Rollen-Mapping anzeigen."""
        await self.wow_listrankmap(ctx)

    @wow.command(
        name="botsetup",
        description="Blizzard API: Client-ID und Secret (nur Bot-Besitzer).",
    )
    @commands.is_owner()
    @app_commands.describe(
        client_id="Blizzard Developer Portal Client-ID",
        client_secret="Blizzard Developer Portal Client Secret",
    )
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

    @wow.command(
        name="mastersetup",
        description="Globale Defaults: Sprache, Region, Version, Dashboard (nur Bot-Besitzer).",
    )
    @commands.is_owner()
    @app_commands.describe(
        default_language="Standard de-DE oder en-US für neue Servereinträge",
        default_region="Standard-API-Region, z. B. eu",
        default_version="Standard-Spielversion, z. B. retail",
        dashboard_enabled="Web-Dashboard für WoW-Cog aktivieren",
    )
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

    @commands.hybrid_command(
        name="wow-botsetup",
        description="Blizzard API: Client-ID und Secret (nur Bot-Besitzer).",
    )
    @commands.is_owner()
    @app_commands.describe(
        client_id="Blizzard Developer Portal Client-ID",
        client_secret="Blizzard Developer Portal Client Secret",
    )
    async def wow_botsetup_direct(
        self,
        ctx: commands.Context,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Blizzard API: Client-ID und Secret (nur Bot-Besitzer)."""
        await self.wow_botsetup(ctx, client_id, client_secret)

    @commands.hybrid_command(
        name="wow-mastersetup",
        description="Globale Defaults: Sprache, Region, Version, Dashboard (nur Bot-Besitzer).",
    )
    @commands.is_owner()
    @app_commands.describe(
        default_language="Standard de-DE oder en-US für neue Servereinträge",
        default_region="Standard-API-Region, z. B. eu",
        default_version="Standard-Spielversion, z. B. retail",
        dashboard_enabled="Web-Dashboard für WoW-Cog aktivieren",
    )
    async def wow_mastersetup_direct(
        self,
        ctx: commands.Context,
        default_language: str = "de-DE",
        default_region: str = "eu",
        default_version: str = "retail",
        dashboard_enabled: bool = True,
    ) -> None:
        """Globale Defaults: Sprache, Region, Version, Dashboard (nur Bot-Besitzer)."""
        await self.wow_mastersetup(
            ctx,
            default_language=default_language,
            default_region=default_region,
            default_version=default_version,
            dashboard_enabled=dashboard_enabled,
        )

    @wow.command(
        name="onboarding-setup",
        description="Onboarding-Kanal und Rollen per Chat-Wizard einrichten.",
    )
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

    @commands.hybrid_command(
        name="wow-onboarding-setup",
        description="Onboarding-Kanal und Rollen per Chat-Wizard einrichten.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_onboarding_setup_direct(self, ctx: commands.Context) -> None:
        """Onboarding-Kanal und Rollen per Chat-Wizard einrichten."""
        await self.wow_onboarding_setup(ctx)

    @wow.command(
        name="simulate-join",
        description="Onboarding-Flow für ein Mitglied testen (ohne echten Join).",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(member="Mitglied, für das die Simulation läuft")
    async def wow_simulate_join(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._send_private_ack(ctx, f"Simuliere Join-Onboarding fuer {member.mention}...")
        await self._run_onboarding_flow(member, simulated=True)
        await self._send_private_ack(ctx, "Simulation abgeschlossen.")

    @commands.hybrid_command(
        name="wow-simulate-join",
        description="Onboarding-Flow für ein Mitglied testen (ohne echten Join).",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(member="Mitglied, für das die Simulation läuft")
    async def wow_simulate_join_direct(self, ctx: commands.Context, member: discord.Member) -> None:
        """Onboarding-Flow für ein Mitglied testen (ohne echten Join)."""
        await self.wow_simulate_join(ctx, member)

    @wow.command(
        name="registrations",
        description="Alle gespeicherten Onboarding-Registrierungen dieses Servers listen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_registrations(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            await ctx.send(await self._t(ctx, "server_only"))
            return
        all_members = await self.config.all_members(ctx.guild)
        lines = []
        for member_id, payload in all_members.items():
            reg = payload.get("registration", {})
            if not reg:
                continue
            user = ctx.guild.get_member(int(member_id))
            user_label = user.mention if user else f"<@{member_id}>"
            reg_at = reg.get("registered_at", "-")
            game = payload.get("selected_game", "retail")
            reg_type = reg.get("type", "unknown")
            char_name = reg.get("char_name", "")
            details = f"{user_label} - {reg_at} - {game} - {reg_type}"
            if reg_type == "member" and char_name:
                details += f" ({char_name})"
            lines.append(details)
        if not lines:
            await ctx.send("Keine Registrierungen vorhanden.")
            return
        message = "Registrierungen:\n" + "\n".join(f"- {line}" for line in lines[:100])
        await ctx.send(message)

    @commands.hybrid_command(
        name="wow-registrations",
        description="Alle gespeicherten Onboarding-Registrierungen dieses Servers listen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def wow_registrations_direct(self, ctx: commands.Context) -> None:
        """Alle gespeicherten Onboarding-Registrierungen dieses Servers listen."""
        await self.wow_registrations(ctx)

    @wow.command(
        name="delregistration",
        description="Onboarding-Registrierung und Spielwahl eines Mitglieds löschen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(member="Mitglied, dessen Registrierung gelöscht wird")
    async def wow_delregistration(self, ctx: commands.Context, member: discord.Member) -> None:
        if not ctx.guild:
            await ctx.send(await self._t(ctx, "server_only"))
            return
        await self.config.member(member).registration.clear()
        await self.config.member(member).selected_game.clear()
        await ctx.send(f"Registrierung von {member.mention} wurde entfernt.")

    @commands.hybrid_command(
        name="wow-delregistration",
        description="Onboarding-Registrierung und Spielwahl eines Mitglieds löschen.",
    )
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(member="Mitglied, dessen Registrierung gelöscht wird")
    async def wow_delregistration_direct(self, ctx: commands.Context, member: discord.Member) -> None:
        """Onboarding-Registrierung und Spielwahl eines Mitglieds löschen."""
        await self.wow_delregistration(ctx, member)

    @wow.command(
        name="dashboard-status",
        description="Prüfen, ob Dashboard-Cog und WoW-Webseiten erreichbar sind (Bot-Besitzer).",
    )
    @commands.is_owner()
    async def wow_dashboard_status(self, ctx: commands.Context) -> None:
        dashboard_cog = self._get_dashboard_cog()
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

    @commands.hybrid_command(
        name="wow-chars-panel",
        description="Interaktives Menü: Chars verknüpfen, Main setzen, Liste, entfernen (ephemeral).",
    )
    @commands.guild_only()
    async def wow_chars_panel_hybrid(self, ctx: commands.Context) -> None:
        """Öffnet das Charakter-Panel (Slash empfohlen; Prefix versucht DM)."""
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send(await self._t(ctx, "server_only"))
            return
        interaction = getattr(ctx, "interaction", None)
        if interaction is not None:
            await interaction.response.send_message(
                PANEL_INTRO,
                ephemeral=True,
                view=CharMainMenuView(self, ctx.guild, ctx.author),
            )
            return
        try:
            dm = await ctx.author.create_dm()
            await dm.send(PANEL_INTRO, view=CharMainMenuView(self, ctx.guild, ctx.author))
        except discord.HTTPException:
            await ctx.send(
                "DM nicht möglich — nutze bitte **`/wow-chars-panel`** auf dem Server (ephemerales Menü)."
            )

    @app_commands.command(name="wow-user", description="WoW: Panel, deine Char-Liste und Rang-Sync.")
    @app_commands.guild_only()
    @app_commands.describe(action="Aktion")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Panel (interaktives Menü)", value="panel"),
            app_commands.Choice(name="Meine Chars (Liste)", value="list_my"),
            app_commands.Choice(name="Rang-Sync (meine Mains)", value="sync_my_profile"),
        ]
    )
    async def slash_wow_user(self, interaction: discord.Interaction, action: str) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        if action == "panel":
            await interaction.response.send_message(
                PANEL_INTRO,
                ephemeral=True,
                view=CharMainMenuView(self, interaction.guild, interaction.user),
            )
            return
        if action == "list_my":
            await interaction.response.defer(ephemeral=True)
            text = await self._format_user_char_list_ephemeral(
                interaction.guild,
                interaction.user,
                header_user=False,
            )
            chars_none = await self._t_from_guild(interaction.guild, interaction.user, "chars_none")
            display = text if text else chars_none
            for chunk in [display[i : i + 1900] for i in range(0, len(display), 1900)] or ["—"]:
                await interaction.followup.send(chunk, ephemeral=True)
            return
        if action == "sync_my_profile":
            await interaction.response.defer(ephemeral=True)
            report = await self._slash_admin_sync_report_for_member(interaction.guild, interaction.user)
            await interaction.followup.send(report[:1900], ephemeral=True)
            return
        await interaction.response.send_message("Unbekannte Aktion.", ephemeral=True)

    @app_commands.command(
        name="wow-admin",
        description="Officer: Charaktere listen, verwalten und Rang-Sync (Manage Server).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(action="Aktion — bei Bedarf folgt eine zweite Auswahl (Dropdown).")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Übersicht (alle / Mitglieder wählen)", value="list"),
            app_commands.Choice(name="Char von Mitglied entfernen", value="remove_char_member"),
            app_commands.Choice(name="Char für Mitglied hinzufügen (Roster)", value="add_char_member"),
            app_commands.Choice(name="Main für Mitglied setzen (Panel)", value="set_main_member"),
            app_commands.Choice(name="Rang-Sync für ein Mitglied", value="sync_specific_member"),
            app_commands.Choice(name="Rang-Sync für alle (mit Main)", value="sync_all_members"),
        ]
    )
    async def slash_wow_admin(self, interaction: discord.Interaction, action: str) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        if not officer_can_manage_characters(interaction.user):
            await interaction.response.send_message(
                "Nur für Mitglieder mit **Server verwalten** (oder Administrator).",
                ephemeral=True,
            )
            return
        if action == "list":
            await interaction.response.send_message(
                "Listen-Art wählen:",
                ephemeral=True,
                view=SlashWowAdminListView(self, interaction.guild, interaction.user),
            )
            return
        if action == "remove_char_member":
            await interaction.response.send_message(
                "Welches Mitglied? (Dropdown)",
                ephemeral=True,
                view=SlashWowAdminMemberPickView(
                    self, interaction.guild, interaction.user, mode="remove_char_member"
                ),
            )
            return
        if action == "add_char_member":
            await interaction.response.send_message(
                "Für welches Mitglied soll ein Char aus dem Roster verknüpft werden?",
                ephemeral=True,
                view=SlashWowAdminMemberPickView(
                    self, interaction.guild, interaction.user, mode="add_char_member"
                ),
            )
            return
        if action == "set_main_member":
            await interaction.response.send_message(
                "Für welches Mitglied soll der Main gesetzt werden?",
                ephemeral=True,
                view=SlashWowAdminMemberPickView(
                    self, interaction.guild, interaction.user, mode="set_main_member"
                ),
            )
            return
        if action == "sync_specific_member":
            await interaction.response.send_message(
                "Welches Mitglied synchronisieren?",
                ephemeral=True,
                view=SlashWowAdminMemberPickView(
                    self, interaction.guild, interaction.user, mode="sync_specific_member"
                ),
            )
            return
        if action == "sync_all_members":
            await interaction.response.send_message(
                "Alle Mitglieder mit verknüpften Chars **und** gesetztem Main werden nacheinander synchronisiert "
                "(kann bei großen Gilden lange dauern). Bitte bestätigen:",
                ephemeral=True,
                view=SlashWowAdminSyncAllConfirmView(self, interaction.guild, interaction.user),
            )
            return
        await interaction.response.send_message("Unbekannte Aktion.", ephemeral=True)

    @wow_char_grp.command(name="meine-chars", description="Deine verknüpften Chars (nur du siehst das)")
    @app_commands.guild_only()
    async def slash_wow_char_mine(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        text = await self._format_user_char_list_ephemeral(
            interaction.guild, interaction.user, header_user=False
        )
        await interaction.response.send_message(text, ephemeral=True)

    @wow_char_officer_grp.command(name="liste", description="Übersicht: alle oder ausgewählte Mitglieder")
    @app_commands.guild_only()
    async def slash_wow_char_officer_list(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        if not officer_can_manage_characters(interaction.user):
            await interaction.response.send_message("Keine Berechtigung (Manage Server).", ephemeral=True)
            return
        await interaction.response.send_message(
            "Wähle eine Option:",
            ephemeral=True,
            view=OfficerListMenuView(self, interaction.guild, interaction.user),
        )

    @wow_char_officer_grp.command(
        name="meine-chars",
        description="Zeigt deine eigenen verknüpften Chars (zum Abgleich)",
    )
    @app_commands.guild_only()
    async def slash_wow_char_officer_self(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        if not officer_can_manage_characters(interaction.user):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        text = await self._format_user_char_list_ephemeral(
            interaction.guild, interaction.user, header_user=True
        )
        await interaction.response.send_message(text, ephemeral=True)

    @wow_char_officer_grp.command(
        name="char-entfernen",
        description="Chars eines Mitglieds entfernen (User erhält DM mit Grund)",
    )
    @app_commands.guild_only()
    @app_commands.describe(mitglied="Discord-Mitglied")
    async def slash_wow_char_officer_remove(
        self,
        interaction: discord.Interaction,
        mitglied: discord.Member,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf einem Server.", ephemeral=True)
            return
        if not officer_can_manage_characters(interaction.user):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        linked = await get_linked_list(self.config.member(mitglied))
        if not linked:
            await interaction.response.send_message(
                f"{mitglied.mention} hat keine verknüpften Chars.",
                ephemeral=True,
            )
            return
        ordered = sorted(linked, key=lambda e: (e["game_type"], e["name"].lower()))
        await interaction.response.send_message(
            "Markiere Charaktere im Dropdown (mehrere Seiten möglich), dann **Grund eingeben …**.",
            ephemeral=True,
            view=LinkedRemovePageView(
                self,
                interaction.guild,
                interaction.user,
                ordered,
                0,
                officer_mode=True,
                officer=interaction.user,
                target=mitglied,
                accumulated=set(),
            ),
        )

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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
.wow-wrap {{
  font-family: 'Inter', sans-serif;
  background: rgba(18, 23, 33, 0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 24px;
  color: #f3e9d2;
  box-shadow: 0 8px 32px 0 rgba(0,0,0,.3);
}}
.wow-wrap h2, .wow-wrap h3 {{ color: #ffffff; margin: 4px 0 16px 0; font-weight: 600; letter-spacing: -0.02em; }}
.wow-wrap p {{ margin-top: 0; margin-bottom: 14px; line-height: 1.5; color: #a0aec0; }}
.wow-wrap label {{ color: #cbd5e0; font-weight: 500; font-size: 13.5px; margin-bottom: 6px; display: inline-block; }}
.wow-wrap input, .wow-wrap select {{
  background: rgba(0, 0, 0, 0.25);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 10px 14px;
  min-width: 360px;
  font-size: 14px;
  transition: all 0.2s ease;
  box-sizing: border-box;
}}
.wow-wrap input:focus, .wow-wrap select:focus {{
  outline: none;
  border-color: #4299e1;
  box-shadow: 0 0 0 3px rgba(66, 153, 225, 0.25);
  background: rgba(0, 0, 0, 0.35);
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
                    new_profile_version = wtforms.SelectField("Create New Profile For Version")
                    region = wtforms.StringField("Profile Region")
                    version = wtforms.SelectField(
                        "Profile Version",
                        choices=[
                            ("retail", "retail"),
                            ("classic", "classic"),
                            ("classic_era", "classic_era"),
                            ("mop_classic", "mop_classic"),
                            ("sod", "sod"),
                        ],
                    )
                    realm = wtforms.StringField("Realm")
                    guild_name = wtforms.StringField("Guild Name")
                    welcome_text_de = wtforms.StringField("Onboarding Text DE")
                    welcome_text_en = wtforms.StringField("Onboarding Text EN")
                    guest_role_id = wtforms.SelectField("Guest Role")
                    create_guest_role = wtforms.BooleanField("Create Guest Role if missing")
                    member_role_id = wtforms.SelectField("Member Role")
                    create_member_role = wtforms.BooleanField("Create Member Role if missing")
                    onboarding_new_role_id = wtforms.SelectField("Onboarding New Role")
                    create_onboarding_new_role = wtforms.BooleanField(
                        "Create Onboarding New Role if missing"
                    )
                    onboarding_complete_role_id = wtforms.SelectField("Onboarding Complete Role")
                    create_onboarding_complete_role = wtforms.BooleanField(
                        "Create Onboarding Complete Role if missing"
                    )
                    onboarding_channel_id = wtforms.SelectField("Onboarding Channel")
                    create_onboarding_channel = wtforms.BooleanField(
                        "Create Onboarding Channel if missing"
                    )
                    manual_review_channel_id = wtforms.SelectField("Manual Review Channel")
                    create_manual_review_channel = wtforms.BooleanField(
                        "Create Manual Review Channel if missing"
                    )
                    raid_guest_channel_id = wtforms.SelectField("Raid Guest Channel")
                    create_raid_guest_channel = wtforms.BooleanField(
                        "Create Raid Guest Channel if missing"
                    )
                    rule_channel_id = wtforms.SelectField("Rules Channel")
                    rule_emoji = wtforms.StringField("Rules Confirmation Emoji")
                    target_category_id = wtforms.SelectField("Target Category for new channels")
                    guest_role_name = wtforms.StringField("Create Guest Role Name")
                    member_role_name = wtforms.StringField("Create Member Role Name")
                    onboarding_new_role_name = wtforms.StringField("Create Onboarding New Role Name")
                    onboarding_complete_role_name = wtforms.StringField("Create Onboarding Complete Role Name")
                    onboarding_channel_name = wtforms.StringField("Create Onboarding Channel Name")
                    manual_review_channel_name = wtforms.StringField("Create Manual Review Channel Name")
                    raid_guest_channel_name = wtforms.StringField("Create Raid Guest Channel Name")
                    map_rank_index = wtforms.SelectField("Guild Rank Index (0-9)")
                    map_rank_title = wtforms.StringField("Rank Title (optional)")
                    map_role_id = wtforms.SelectField("Discord Role for this rank")
                    remove_rank_index = wtforms.SelectField("Remove mapping by rank index")
                    remove_registration_user_id = wtforms.SelectField("Remove registration entry")
                    confirm_remove_registration = wtforms.BooleanField(
                        "I understand this permanently removes the registration entry"
                    )
                    load_profile = wtforms.SubmitField("Load Selected Profile")
                    apply_rank_mapping = wtforms.SubmitField("Apply Rank Mapping")
                    remove_rank_mapping = wtforms.SubmitField("Remove Rank Mapping")
                    remove_registration = wtforms.SubmitField("Remove Registration Entry")
                    officer_character_notify_channel_id = wtforms.SelectField(
                        "Officer channel (member left + linked chars notice)"
                    )
                    duplicate_character_message = wtforms.TextAreaField(
                        "Message: character already linked / invalid"
                    )
                    member_left_characters_notice = wtforms.TextAreaField(
                        "Message: member left (vars: {user}, {username}, {chars})"
                    )
                    admin_removed_char_dm = wtforms.TextAreaField(
                        "DM text after officer removed chars (vars: {chars}, {reason}, {officer})"
                    )
                    rank_protected_notify_channel_id = wtforms.SelectField(
                        "Channel: protected-rank notices (no auto Discord role)"
                    )
                    protected_rank_lines = wtforms.TextAreaField(
                        "Protected WoW ranks for active profile (one per line: rank title or 0–9)"
                    )
                    protected_rank_sync_notice = wtforms.TextAreaField(
                        "Template: protected rank notice ({member},{user},{username},{user_id},{game},{char},{rank},{profile})"
                    )
                    save_protected_ranks = wtforms.SubmitField("Save Protected Ranks + Notice")
                    submit = wtforms.SubmitField("Save Guild Settings")

                form = GuildForm()
                wow_profiles = cfg.get("wow_profiles", {})
                active_key = cfg.get("active_profile_key", "") or next(iter(wow_profiles.keys()), "retail")
                if active_key not in wow_profiles and wow_profiles:
                    active_key = next(iter(wow_profiles.keys()))
                wow = wow_profiles.get(active_key, cfg.get("wow", {}))
                roles = cfg.get("roles", {})
                channels = cfg.get("channels", {})
                onboarding = cfg.get("onboarding", {})
                role_choices = [("0", "-- none --")] + [
                    (str(role.id), role.name[:80])
                    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)
                ]
                channel_choices = [("0", "-- none --")] + [
                    (str(channel.id), f"#{channel.name}") for channel in guild.text_channels
                ]
                category_choices = [("0", "-- no category --")] + [
                    (str(category.id), f"{category.name} ({category.id})") for category in guild.categories
                ]
                profile_choices = [(k, k) for k in sorted(wow_profiles.keys())] or [("retail", "retail")]
                form.profile_key.choices = profile_choices + [("__new__", "+ create new profile")]
                all_versions = ["retail", "classic", "classic_era", "mop_classic", "sod"]
                missing_versions = [v for v in all_versions if v not in wow_profiles]
                form.new_profile_version.choices = (
                    [(v, v) for v in missing_versions]
                    if missing_versions
                    else [("__none__", "all versions already configured")]
                )
                form.guest_role_id.choices = role_choices
                form.member_role_id.choices = role_choices
                form.onboarding_new_role_id.choices = role_choices
                form.onboarding_complete_role_id.choices = role_choices
                form.onboarding_channel_id.choices = channel_choices
                form.manual_review_channel_id.choices = channel_choices
                form.raid_guest_channel_id.choices = channel_choices
                form.rule_channel_id.choices = channel_choices
                form.target_category_id.choices = category_choices
                form.map_role_id.choices = role_choices
                form.map_rank_index.choices = [(str(i), str(i)) for i in range(10)]
                form.remove_rank_index.choices = [("__none__", "-- select --")] + [
                    (str(i), str(i)) for i in range(10)
                ]
                all_members = await self.config.all_members(guild)
                reg_choices = [("0", "-- none --")]
                for member_id, payload in all_members.items():
                    if payload.get("registration"):
                        m_obj = guild.get_member(int(member_id))
                        label = (
                            f"{m_obj.display_name} ({m_obj.id})"
                            if m_obj is not None
                            else f"{member_id}"
                        )
                        reg_choices.append((str(member_id), label))
                form.remove_registration_user_id.choices = reg_choices
                form.officer_character_notify_channel_id.choices = channel_choices
                form.rank_protected_notify_channel_id.choices = channel_choices
                tmpl = cfg.get("templates", {})
                if method.upper() == "GET":
                    form.language.data = cfg.get("language", "de-DE")
                    form.profile_key.data = active_key
                    form.new_profile_version.data = (
                        missing_versions[0] if missing_versions else "__none__"
                    )
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
                    rules_cfg = cfg.get("rules", {})
                    form.rule_channel_id.data = str(rules_cfg.get("rule_channel_id", 0))
                    form.rule_emoji.data = str(rules_cfg.get("rule_emoji", "✅"))
                    form.create_guest_role.data = False
                    form.create_member_role.data = False
                    form.create_onboarding_new_role.data = False
                    form.create_onboarding_complete_role.data = False
                    form.create_onboarding_channel.data = False
                    form.create_manual_review_channel.data = False
                    form.create_raid_guest_channel.data = False
                    form.target_category_id.data = "0"
                    form.guest_role_name.data = "guest"
                    form.member_role_name.data = "guild-member"
                    form.onboarding_new_role_name.data = "onboarding-new"
                    form.onboarding_complete_role_name.data = "onboarding-complete"
                    form.onboarding_channel_name.data = "onboarding-private"
                    form.manual_review_channel_name.data = "wow-manual-review"
                    form.raid_guest_channel_name.data = "wow-raid-guests"
                    form.map_rank_index.data = "0"
                    form.map_rank_title.data = ""
                    form.map_role_id.data = "0"
                    form.remove_rank_index.data = "__none__"
                    form.remove_registration_user_id.data = "0"
                    form.confirm_remove_registration.data = False
                    form.officer_character_notify_channel_id.data = str(
                        channels.get("officer_character_notify_channel_id", 0)
                    )
                    form.duplicate_character_message.data = tmpl.get(
                        "duplicate_character_message",
                        "",
                    )
                    form.member_left_characters_notice.data = tmpl.get(
                        "member_left_characters_notice",
                        "",
                    )
                    form.admin_removed_char_dm.data = tmpl.get("admin_removed_char_dm", "")
                    form.rank_protected_notify_channel_id.data = str(
                        channels.get("rank_protected_notify_channel_id", 0)
                    )
                    pr_lines = (cfg.get("protected_rank_titles_by_profile") or {}).get(active_key, [])
                    if isinstance(pr_lines, str):
                        pr_lines = [pr_lines]
                    form.protected_rank_lines.data = (
                        "\n".join(str(x) for x in pr_lines) if isinstance(pr_lines, (list, tuple)) else ""
                    )
                    form.protected_rank_sync_notice.data = tmpl.get("protected_rank_sync_notice", "")

                if form.load_profile.data:
                    selected_key = str(form.profile_key.data or "").strip().lower()
                    if selected_key and selected_key != "__new__" and selected_key in wow_profiles:
                        cfg["active_profile_key"] = selected_key
                        cfg["wow"] = wow_profiles[selected_key]
                        await self.config.guild(guild).set(cfg)
                        return {
                            "status": 0,
                            "notifications": [
                                {"message": f"Profile `{selected_key}` loaded.", "category": "success"}
                            ],
                            "redirect_url": kwargs.get("request_url"),
                        }
                    return {
                        "status": 0,
                        "notifications": [
                            {
                                "message": "Select an existing profile to load.",
                                "category": "warning",
                            }
                        ],
                        "redirect_url": kwargs.get("request_url"),
                    }

                if form.apply_rank_mapping.data:
                    profile_key_for_map = cfg.get("active_profile_key", active_key) or "retail"
                    rank_titles_by_profile = cfg.get("rank_titles_by_profile", {})
                    rank_mapping_by_profile = cfg.get("rank_mapping_by_profile", {})
                    profile_titles = rank_titles_by_profile.get(profile_key_for_map, {})
                    profile_mapping = rank_mapping_by_profile.get(profile_key_for_map, {})
                    rank_idx = str(form.map_rank_index.data or "0")
                    role_id = int(form.map_role_id.data or 0)
                    if role_id == 0:
                        return {
                            "status": 0,
                            "notifications": [{"message": "Please select a role for mapping.", "category": "warning"}],
                            "redirect_url": kwargs.get("request_url"),
                        }
                    rank_title = str(form.map_rank_title.data or "").strip()
                    if not rank_title:
                        rank_title = f"Rank {rank_idx}"
                    profile_titles[rank_idx] = rank_title
                    profile_mapping[rank_title] = role_id
                    rank_titles_by_profile[profile_key_for_map] = profile_titles
                    rank_mapping_by_profile[profile_key_for_map] = profile_mapping
                    cfg["rank_titles_by_profile"] = rank_titles_by_profile
                    cfg["rank_mapping_by_profile"] = rank_mapping_by_profile
                    await self.config.guild(guild).set(cfg)
                    role = guild.get_role(role_id)
                    role_name = role.mention if role else f"`{role_id}`"
                    return {
                        "status": 0,
                        "notifications": [
                            {
                                "message": f"Rank mapping set for {profile_key_for_map}: {rank_title} -> {role_name}",
                                "category": "success",
                            }
                        ],
                        "redirect_url": kwargs.get("request_url"),
                    }

                if form.remove_rank_mapping.data:
                    profile_key_for_map = cfg.get("active_profile_key", active_key) or "retail"
                    rank_idx = str(form.remove_rank_index.data or "__none__")
                    if rank_idx == "__none__":
                        return {
                            "status": 0,
                            "notifications": [{"message": "Select a rank index to remove.", "category": "warning"}],
                            "redirect_url": kwargs.get("request_url"),
                        }
                    rank_titles_by_profile = cfg.get("rank_titles_by_profile", {})
                    rank_mapping_by_profile = cfg.get("rank_mapping_by_profile", {})
                    profile_titles = rank_titles_by_profile.get(profile_key_for_map, {})
                    profile_mapping = rank_mapping_by_profile.get(profile_key_for_map, {})
                    rank_title = profile_titles.pop(rank_idx, f"Rank {rank_idx}")
                    profile_mapping.pop(rank_title, None)
                    profile_mapping.pop(f"Rank {rank_idx}", None)
                    rank_titles_by_profile[profile_key_for_map] = profile_titles
                    rank_mapping_by_profile[profile_key_for_map] = profile_mapping
                    cfg["rank_titles_by_profile"] = rank_titles_by_profile
                    cfg["rank_mapping_by_profile"] = rank_mapping_by_profile
                    await self.config.guild(guild).set(cfg)
                    return {
                        "status": 0,
                        "notifications": [
                            {"message": f"Removed rank mapping for index {rank_idx}.", "category": "success"}
                        ],
                        "redirect_url": kwargs.get("request_url"),
                    }

                if form.save_protected_ranks.data:
                    profile_key_for_prot = str(cfg.get("active_profile_key", active_key) or "retail")
                    lines = str(form.protected_rank_lines.data or "").splitlines()
                    cleaned = [ln.strip() for ln in lines if ln.strip()]
                    pr = cfg.setdefault("protected_rank_titles_by_profile", {})
                    pr[profile_key_for_prot] = cleaned
                    cfg["protected_rank_titles_by_profile"] = pr
                    ch = dict(cfg.get("channels") or {})
                    ch["rank_protected_notify_channel_id"] = int(
                        form.rank_protected_notify_channel_id.data or 0
                    )
                    cfg["channels"] = ch
                    cfg.setdefault("templates", {})["protected_rank_sync_notice"] = str(
                        form.protected_rank_sync_notice.data or ""
                    ).strip()
                    await self.config.guild(guild).set(cfg)
                    return {
                        "status": 0,
                        "notifications": [
                            {
                                "message": f"Protected ranks saved for profile `{profile_key_for_prot}`.",
                                "category": "success",
                            }
                        ],
                        "redirect_url": kwargs.get("request_url"),
                    }

                if form.remove_registration.data:
                    target_member_id = int(form.remove_registration_user_id.data or 0)
                    if target_member_id == 0:
                        return {
                            "status": 0,
                            "notifications": [{"message": "Select a registration entry to remove.", "category": "warning"}],
                            "redirect_url": kwargs.get("request_url"),
                        }
                    if not bool(form.confirm_remove_registration.data):
                        return {
                            "status": 0,
                            "notifications": [
                                {
                                    "message": "Please tick the confirmation checkbox before deleting.",
                                    "category": "warning",
                                }
                            ],
                            "redirect_url": kwargs.get("request_url"),
                        }
                    m_obj = guild.get_member(target_member_id)
                    if m_obj is not None:
                        await self.config.member(m_obj).registration.clear()
                        await self.config.member(m_obj).selected_game.clear()
                    return {
                        "status": 0,
                        "notifications": [
                            {"message": f"Removed registration for {target_member_id}.", "category": "success"}
                        ],
                        "redirect_url": kwargs.get("request_url"),
                    }

                if form.validate_on_submit():
                    cfg["language"] = form.language.data if form.language.data in ("de-DE", "en-US") else "de-DE"
                    if form.profile_key.data == "__new__":
                        selected_new = str(form.new_profile_version.data or "").strip().lower()
                        if selected_new == "__none__" or selected_new not in missing_versions:
                            return {
                                "status": 0,
                                "notifications": [
                                    {
                                        "message": "No free game version available for a new profile.",
                                        "category": "warning",
                                    }
                                ],
                                "redirect_url": kwargs.get("request_url"),
                            }
                        profile_key = selected_new
                    else:
                        profile_key = str(form.profile_key.data or form.version.data or "retail").strip().lower()
                    bot_setup = await self.config.bot_setup()
                    default_region = str(bot_setup.get("default_region", "eu")).strip().lower()
                    default_language = bot_setup.get("default_language", "de-DE")
                    if default_language in ("de-DE", "en-US"):
                        cfg["language"] = default_language
                    profile = {
                        "region": str(form.region.data or default_region).strip().lower(),
                        "version": str(form.version.data or profile_key or "retail").strip().lower(),
                        "realm": str(form.realm.data or "").strip(),
                        "guild_name": str(form.guild_name.data or "").strip(),
                    }
                    cfg.setdefault("wow_profiles", {})
                    cfg["wow_profiles"][profile_key] = profile
                    # Immediately switch active profile to the selected/new one.
                    cfg["active_profile_key"] = profile_key
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
                    ch_merge = dict(cfg.get("channels") or {})
                    ch_merge.update(
                        {
                            "onboarding_channel_id": int(form.onboarding_channel_id.data or 0),
                            "manual_review_channel_id": int(form.manual_review_channel_id.data or 0),
                            "raid_guest_channel_id": int(form.raid_guest_channel_id.data or 0),
                            "officer_character_notify_channel_id": int(
                                form.officer_character_notify_channel_id.data or 0
                            ),
                            "rank_protected_notify_channel_id": int(
                                form.rank_protected_notify_channel_id.data or 0
                            ),
                        }
                    )
                    cfg["channels"] = ch_merge
                    cfg["rules"] = {
                        "rule_channel_id": int(form.rule_channel_id.data or 0),
                        "rule_emoji": str(form.rule_emoji.data or "✅").strip() or "✅",
                    }
                    cfg.setdefault("templates", {})
                    cfg["templates"]["duplicate_character_message"] = str(
                        form.duplicate_character_message.data or ""
                    ).strip()
                    cfg["templates"]["member_left_characters_notice"] = str(
                        form.member_left_characters_notice.data or ""
                    ).strip()
                    cfg["templates"]["admin_removed_char_dm"] = str(
                        form.admin_removed_char_dm.data or ""
                    ).strip()
                    cfg["templates"]["protected_rank_sync_notice"] = str(
                        form.protected_rank_sync_notice.data or ""
                    ).strip()
                    lines_prot = str(form.protected_rank_lines.data or "").splitlines()
                    cleaned_prot = [ln.strip() for ln in lines_prot if ln.strip()]
                    pr_save = cfg.setdefault("protected_rank_titles_by_profile", {})
                    pr_save[profile_key] = cleaned_prot
                    cfg["protected_rank_titles_by_profile"] = pr_save
                    notifications = []
                    category = None
                    try:
                        category = guild.get_channel(int(form.target_category_id.data or 0))
                        if category and not isinstance(category, discord.CategoryChannel):
                            category = None
                    except Exception:
                        category = None

                    role_create_map = [
                        ("guest_role_id", form.guest_role_name.data or "guest", bool(form.create_guest_role.data)),
                        (
                            "member_role_id",
                            form.member_role_name.data or "guild-member",
                            bool(form.create_member_role.data),
                        ),
                        (
                            "onboarding_new_role_id",
                            form.onboarding_new_role_name.data or "onboarding-new",
                            bool(form.create_onboarding_new_role.data),
                        ),
                        (
                            "onboarding_complete_role_id",
                            form.onboarding_complete_role_name.data or "onboarding-complete",
                            bool(form.create_onboarding_complete_role.data),
                        ),
                    ]
                    for key, role_name, should_create in role_create_map:
                        if cfg["roles"].get(key, 0) or not should_create:
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
                        (
                            "onboarding_channel_id",
                            form.onboarding_channel_name.data or "onboarding-private",
                            bool(form.create_onboarding_channel.data),
                        ),
                        (
                            "manual_review_channel_id",
                            form.manual_review_channel_name.data or "wow-manual-review",
                            bool(form.create_manual_review_channel.data),
                        ),
                        (
                            "raid_guest_channel_id",
                            form.raid_guest_channel_name.data or "wow-raid-guests",
                            bool(form.create_raid_guest_channel.data),
                        ),
                    ]
                    for key, channel_name, should_create in channel_create_map:
                        if cfg["channels"].get(key, 0) or not should_create:
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

                active_profile_for_ui = cfg.get("active_profile_key", active_key)
                rank_titles_by_profile = cfg.get("rank_titles_by_profile", {})
                rank_mapping_by_profile = cfg.get("rank_mapping_by_profile", {})
                profile_titles_ui = rank_titles_by_profile.get(active_profile_for_ui, {})
                profile_mapping_ui = rank_mapping_by_profile.get(active_profile_for_ui, {})
                current_rank_rows = []
                for idx in range(10):
                    idx_s = str(idx)
                    title = profile_titles_ui.get(idx_s, f"Rank {idx}")
                    mapped_id = profile_mapping_ui.get(title) or profile_mapping_ui.get(f"Rank {idx}")
                    if mapped_id:
                        role_obj = guild.get_role(int(mapped_id))
                        mapped_label = (
                            html.escape(role_obj.name) if role_obj else f"`{mapped_id}`"
                        )
                    else:
                        mapped_label = "<em>fallback: member default role</em>"
                    current_rank_rows.append(
                        f"<tr><td>{idx}</td><td>{html.escape(str(title))}</td><td>{mapped_label}</td></tr>"
                    )
                current_rank_table = "".join(current_rank_rows)

                reg_count = 0
                all_members_ui = await self.config.all_members(guild)
                for _m_id, _payload in all_members_ui.items():
                    if _payload.get("registration"):
                        reg_count += 1

                source = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
.wow-wrap {{
  font-family: 'Inter', sans-serif;
  background: rgba(18, 23, 33, 0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 24px;
  color: #f3e9d2;
  box-shadow: 0 8px 32px 0 rgba(0,0,0,.3);
}}
.wow-wrap h2, .wow-wrap h3 {{ color: #ffffff; margin: 4px 0 16px 0; font-weight: 600; letter-spacing: -0.02em; }}
.wow-wrap p {{ margin-top: 0; margin-bottom: 14px; line-height: 1.5; color: #a0aec0; }}
.wow-wrap label {{ color: #cbd5e0; font-weight: 500; font-size: 13.5px; margin-bottom: 6px; display: inline-block; }}
.wow-wrap input, .wow-wrap select {{
  background: rgba(0, 0, 0, 0.25);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 10px 14px;
  min-width: 360px;
  font-size: 14px;
  transition: all 0.2s ease;
  box-sizing: border-box;
}}
.wow-wrap input:focus, .wow-wrap select:focus {{
  outline: none;
  border-color: #4299e1;
  box-shadow: 0 0 0 3px rgba(66, 153, 225, 0.25);
  background: rgba(0, 0, 0, 0.35);
}}
.wow-wrap hr {{ border-color: rgba(255,255,255,0.08); opacity: 1; margin: 24px 0; }}
.wow-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 20px;
}}
.wow-card {{
  background: rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 10px;
  padding: 18px;
  transition: all 0.3s ease;
}}
.wow-card:hover {{
  background: rgba(0, 0, 0, 0.2);
  border-color: rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}}
.wow-meta {{
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}}
.wow-badge {{
  background: rgba(66, 153, 225, 0.15);
  border: 1px solid rgba(66, 153, 225, 0.3);
  color: #63b3ed;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}}
.wow-table {{
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  margin-top: 12px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.06);
}}
.wow-table th, .wow-table td {{
  border-bottom: 1px solid rgba(255,255,255,0.06);
  padding: 12px 14px;
  text-align: left;
  font-size: 13.5px;
  background: rgba(0,0,0,0.15);
}}
.wow-table th {{
  background: rgba(0,0,0,0.25);
  font-weight: 600;
  color: #a0aec0;
  text-transform: uppercase;
  font-size: 12px;
  letter-spacing: 0.05em;
}}
</style>
<div class="wow-wrap">
  <h2>WoW Guild Settings</h2>
  <p>Settings for <b>{guild.name}</b> - For the Horde/Alliance dashboard mode.</p>
  <div class="wow-meta">
    <span class="wow-badge">Active profile: <b>{active_profile_for_ui}</b></span>
    <span class="wow-badge">Registrations stored: <b>{reg_count}</b></span>
    <span class="wow-badge">Configured profiles: <b>{len(wow_profiles)}</b></span>
  </div>
  <form method="post">
    {form.hidden_tag()}
    <div class="wow-grid">
      <div class="wow-card">
        <h3>Profile</h3>
        <p><label>Language</label><br>{form.language()}</p>
        <p><label>WoW Profile</label><br>{form.profile_key()}</p>
        <p><small>Select existing profile or choose <b>+ create new profile</b>.</small></p>
        <p><label>Create New Profile For Version</label><br>{form.new_profile_version()}</p>
        <p>{form.load_profile()}</p>
        <p><label>Profile Region</label><br>{form.region()}<br><small>eu, us, kr, tw</small></p>
        <p><label>Profile Version</label><br>{form.version()}</p>
        <p><label>Realm</label><br>{form.realm()}</p>
        <p><label>Guild Name</label><br>{form.guild_name()}</p>
      </div>

      <div class="wow-card">
        <h3>Onboarding Texts</h3>
        <p><label>Onboarding Text DE</label><br>{form.welcome_text_de()}</p>
        <p><label>Onboarding Text EN</label><br>{form.welcome_text_en()}</p>
        <h3>Rules</h3>
        <p><label>Rules Channel</label><br>{form.rule_channel_id()}</p>
        <p><label>Rules Confirmation Emoji</label><br>{form.rule_emoji()}</p>
      </div>

      <div class="wow-card">
        <h3>Discord Roles</h3>
        <p><label>Guest Role</label><br>{form.guest_role_id()}<br><label>{form.create_guest_role()} Auto-create</label></p>
        <p><label>Member Role</label><br>{form.member_role_id()}<br><label>{form.create_member_role()} Auto-create</label></p>
        <p><label>Onboarding New Role</label><br>{form.onboarding_new_role_id()}<br><label>{form.create_onboarding_new_role()} Auto-create</label></p>
        <p><label>Onboarding Complete Role</label><br>{form.onboarding_complete_role_id()}<br><label>{form.create_onboarding_complete_role()} Auto-create</label></p>
      </div>

      <div class="wow-card">
        <h3>Discord Channels</h3>
        <p><label>Onboarding Channel</label><br>{form.onboarding_channel_id()}<br><label>{form.create_onboarding_channel()} Auto-create</label></p>
        <p><label>Manual Review Channel</label><br>{form.manual_review_channel_id()}<br><label>{form.create_manual_review_channel()} Auto-create</label></p>
        <p><label>Raid Guest Channel</label><br>{form.raid_guest_channel_id()}<br><label>{form.create_raid_guest_channel()} Auto-create</label></p>
        <p><label>Officer notify channel</label><br>{form.officer_character_notify_channel_id()}<br><small>Leave / member quit: notice if linked WoW chars existed</small></p>
        <p><label>Protected-rank notify channel</label><br>{form.rank_protected_notify_channel_id()}<br><small>When a member’s ingame rank is protected, no auto role — post here</small></p>
      </div>

      <div class="wow-card">
        <h3>Character linking messages</h3>
        <p><small>Slash <code>/wow-chars-panel</code>, <code>/wow-char</code> / <code>/wow-char-officer</code>.</small></p>
        <p><label>Duplicate / already linked (use &#123;detail&#125;)</label><br>{form.duplicate_character_message(rows=4)}</p>
        <p><label>Member left notice (&#123;user&#125;, &#123;username&#125;, &#123;chars&#125;)</label><br>{form.member_left_characters_notice(rows=3)}</p>
        <p><label>Officer removal DM (&#123;chars&#125;, &#123;reason&#125;, &#123;officer&#125;)</label><br>{form.admin_removed_char_dm(rows=3)}</p>
      </div>

      <div class="wow-card">
        <h3>Auto-Create Names</h3>
        <p><label>Target Category</label><br>{form.target_category_id()}</p>
        <p><label>Guest Role Name</label><br>{form.guest_role_name()}</p>
        <p><label>Member Role Name</label><br>{form.member_role_name()}</p>
        <p><label>Onboarding New Role Name</label><br>{form.onboarding_new_role_name()}</p>
        <p><label>Onboarding Complete Role Name</label><br>{form.onboarding_complete_role_name()}</p>
        <p><label>Onboarding Channel Name</label><br>{form.onboarding_channel_name()}</p>
        <p><label>Manual Review Channel Name</label><br>{form.manual_review_channel_name()}</p>
        <p><label>Raid Guest Channel Name</label><br>{form.raid_guest_channel_name()}</p>
      </div>

      <div class="wow-card">
        <h3>Rank Mapping (0-9)</h3>
        <p><small>Per active profile. Missing mapping uses member default role.</small></p>
        <table class="wow-table">
          <thead><tr><th>Index</th><th>Title</th><th>Mapped Role</th></tr></thead>
          <tbody>{current_rank_table}</tbody>
        </table>
        <p><label>Rank Index</label><br>{form.map_rank_index()}</p>
        <p><label>Rank Title (optional)</label><br>{form.map_rank_title()}</p>
        <p><label>Discord Role</label><br>{form.map_role_id()}</p>
        <p>{form.apply_rank_mapping()}</p>
        <p><label>Remove by Rank Index</label><br>{form.remove_rank_index()}</p>
        <p>{form.remove_rank_mapping()}</p>
      </div>

      <div class="wow-card">
        <h3>Protected WoW ranks (active profile)</h3>
        <p><small>Members with these ingame ranks (match rank title, API name, or guild rank index <b>0–9</b>) do <b>not</b> get automatic Discord rank roles. One entry per line. Load profile first if you edit another version.</small></p>
        <p><label>Protected rank list</label><br>{form.protected_rank_lines(rows=8)}</p>
        <p><label>Officer notice template</label><br>{form.protected_rank_sync_notice(rows=3)}</p>
        <p>{form.save_protected_ranks()}</p>
      </div>
    </div>
    <hr>
    <div class="wow-card">
      <h3>Registration Cleanup</h3>
      <p><label>Registration Entry</label><br>{form.remove_registration_user_id()}</p>
      <p><label>{form.confirm_remove_registration()} Confirm permanent deletion</label></p>
      <p>{form.remove_registration()}</p>
    </div>
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

