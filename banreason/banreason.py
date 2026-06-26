"""BanReason — ban with a preset, queried reason list.

The ``dban`` command's ``reason`` autocompletes from a per-guild preset list, so
moderators pick a consistent reason. Optionally DMs the user the reason before
banning and logs to a mod-log channel. Reasons are managed from the web dashboard
(one per line). Bilingual (DE/EN).
"""
from __future__ import annotations

import logging
from typing import List, Optional

import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dks_dashboard import (
    Field,
    L,
    PanelSchema,
    SubmitResult,
    dashboard_panel,
    register_dashboard,
    tr_lang,
    unregister_dashboard,
)

log = logging.getLogger("red.dks.banreason")


class BanReason(commands.Cog):
    """Ban command with a preset, queried reason list."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xBA4_E5, force_registration=True)
        self.config.register_guild(
            enabled=True,
            language="en-US",
            reasons=[],
            dm_user=True,
            log_channel=None,
        )

    async def cog_load(self) -> None:
        register_dashboard(self)

    def cog_unload(self) -> None:
        unregister_dashboard(self)

    @staticmethod
    def _t(lang: str, de: str, en: str) -> str:
        return de if str(lang).lower().startswith("de") else en

    async def _lang(self, guild) -> str:
        if guild is None:
            return "en-US"
        return await self.config.guild(guild).language()

    # ------------------------------------------------------------------ #
    # Ban command
    # ------------------------------------------------------------------ #
    @commands.hybrid_command(name="dban")
    @commands.admin_or_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    @app_commands.describe(
        member="Member to ban",
        reason="Reason — type to pick from the preset list (free text allowed)",
        delete_days="Delete this many days of their messages (0–7)",
    )
    async def dban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: Optional[str] = None,
        delete_days: Optional[int] = 0,
    ) -> None:
        """Ban a member with a (preset) reason."""
        lang = await self._lang(ctx.guild)
        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            await ctx.send(self._t(lang, "Modul ist deaktiviert.", "Module is disabled."))
            return
        if member == ctx.author:
            await ctx.send(self._t(lang, "Dich selbst? Nein.", "Yourself? No."))
            return
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(self._t(lang, "Diese Person ist hierarchisch über dir.", "That member is above you in the role hierarchy."))
            return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(self._t(lang, "Ich kann diese Person nicht bannen (Rollen-Hierarchie).", "I can't ban that member (role hierarchy)."))
            return
        reason = (reason or self._t(lang, "Kein Grund angegeben", "No reason given")).strip()
        dd = max(0, min(7, int(delete_days or 0)))

        if await conf.dm_user():
            try:
                await member.send(
                    self._t(lang, f"Du wurdest von **{ctx.guild.name}** gebannt.\nGrund: {reason}",
                            f"You were banned from **{ctx.guild.name}**.\nReason: {reason}")
                )
            except discord.HTTPException:
                pass

        try:
            await ctx.guild.ban(member, reason=f"{ctx.author}: {reason}", delete_message_days=dd)
        except discord.HTTPException as e:
            await ctx.send(self._t(lang, f"Bann fehlgeschlagen: {e}", f"Ban failed: {e}"))
            return

        await ctx.send(self._t(lang, f"🔨 **{member}** gebannt. Grund: {reason}", f"🔨 Banned **{member}**. Reason: {reason}"))

        log_id = await conf.log_channel()
        if log_id:
            ch = ctx.guild.get_channel(log_id)
            if ch is not None and ch.permissions_for(ctx.guild.me).send_messages:
                e = discord.Embed(title=self._t(lang, "Bann", "Ban"), colour=discord.Colour.red(), timestamp=discord.utils.utcnow())
                e.add_field(name=self._t(lang, "Benutzer", "User"), value=f"{member} ({member.id})", inline=False)
                e.add_field(name=self._t(lang, "Moderator", "Moderator"), value=ctx.author.mention, inline=True)
                e.add_field(name=self._t(lang, "Grund", "Reason"), value=reason, inline=False)
                try:
                    await ch.send(embed=e)
                except discord.HTTPException:
                    pass

    @dban.autocomplete("reason")
    async def reason_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        reasons = await self.config.guild(interaction.guild).reasons()
        cur = (current or "").lower()
        return [app_commands.Choice(name=r[:100], value=r[:100]) for r in reasons if cur in r.lower()][:25]

    # ------------------------------------------------------------------ #
    # Reason list management
    # ------------------------------------------------------------------ #
    @commands.hybrid_group(name="banreasons", aliases=["banset"])
    @commands.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def banreasons(self, ctx: commands.Context) -> None:
        """Manage the preset ban reasons + settings."""

    @banreasons.command(name="add")
    @app_commands.describe(reason="A preset reason to add")
    async def br_add(self, ctx: commands.Context, *, reason: str) -> None:
        """Add a preset reason."""
        lang = await self._lang(ctx.guild)
        async with self.config.guild(ctx.guild).reasons() as reasons:
            reasons.append(reason.strip())
        await ctx.send(self._t(lang, "Grund hinzugefügt.", "Reason added."))

    @banreasons.command(name="remove")
    @app_commands.describe(index="Position from 'banreasons list' (1-based)")
    async def br_remove(self, ctx: commands.Context, index: int) -> None:
        """Remove a preset reason by its number."""
        lang = await self._lang(ctx.guild)
        async with self.config.guild(ctx.guild).reasons() as reasons:
            if 1 <= index <= len(reasons):
                reasons.pop(index - 1)
                ok = True
            else:
                ok = False
        await ctx.send(self._t(lang, "Entfernt." if ok else "Ungültige Position.", "Removed." if ok else "Invalid position."))

    @banreasons.command(name="list")
    async def br_list(self, ctx: commands.Context) -> None:
        """List the preset reasons."""
        lang = await self._lang(ctx.guild)
        reasons = await self.config.guild(ctx.guild).reasons()
        if not reasons:
            await ctx.send(self._t(lang, "Keine Gründe hinterlegt.", "No preset reasons."))
            return
        body = "\n".join(f"**{i}.** {r}" for i, r in enumerate(reasons, start=1))
        await ctx.send(embed=discord.Embed(title=self._t(lang, "Bann-Gründe", "Ban reasons"), description=body[:4000], colour=await ctx.embed_colour()))

    @banreasons.command(name="enable")
    @app_commands.describe(on_off="Enable or disable the ban command")
    async def br_enable(self, ctx: commands.Context, on_off: bool) -> None:
        """Enable/disable the module."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).enabled.set(on_off)
        state = self._t(lang, "aktiviert" if on_off else "deaktiviert", "enabled" if on_off else "disabled")
        await ctx.send(self._t(lang, f"BanReason **{state}**.", f"BanReason **{state}**."))

    @banreasons.command(name="dm")
    @app_commands.describe(on_off="DM the banned user the reason")
    async def br_dm(self, ctx: commands.Context, on_off: bool) -> None:
        """Toggle DMing the banned user."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).dm_user.set(on_off)
        await ctx.send(self._t(lang, "Gespeichert.", "Saved."))

    @banreasons.command(name="logchannel")
    @app_commands.describe(channel="Mod-log channel (omit to clear)")
    async def br_logchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """Set/clear the mod-log channel."""
        lang = await self._lang(ctx.guild)
        if channel is None:
            await self.config.guild(ctx.guild).log_channel.clear()
            await ctx.send(self._t(lang, "Log-Kanal entfernt.", "Log channel cleared."))
            return
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(self._t(lang, f"Log-Kanal: {channel.mention}", f"Log channel: {channel.mention}"))

    @banreasons.command(name="language")
    @app_commands.describe(language="Output language: de-DE or en-US")
    async def br_language(self, ctx: commands.Context, language: str) -> None:
        """Set the output language for this server."""
        language = "de-DE" if language.lower().startswith("de") else "en-US"
        await self.config.guild(ctx.guild).language.set(language)
        await ctx.send(self._t(language, "Sprache: Deutsch", "Language: English"))

    # ------------------------------------------------------------------ #
    # Dashboard panel
    # ------------------------------------------------------------------ #
    @dashboard_panel("banreason", L("Ban-Gründe", "Ban reasons"), mount="guild_settings", permission="guild_admin", order=85)
    async def settings_panel(self, ctx):
        conf = self.config.guild(ctx.guild)
        lang = await conf.language()
        reasons = await conf.reasons()
        return PanelSchema(
            description=tr_lang(
                lang,
                "Vorgefertigte Bann-Gründe (eine pro Zeile). Sie erscheinen als Autocomplete bei `/dban`.",
                "Preset ban reasons (one per line). They show up as autocomplete on `/dban`.",
            ),
            fields=[
                Field.switch("enabled", L("Aktiviert", "Enabled"), value=bool(await conf.enabled())),
                Field.switch("dm_user", L("Gebannten per DM informieren", "DM the banned user"), value=bool(await conf.dm_user())),
                Field.channel("log_channel", L("Log-Kanal", "Log channel"), value=str(await conf.log_channel() or "")),
                Field.textarea("reasons", L("Gründe (eine pro Zeile)", "Reasons (one per line)"), value="\n".join(reasons)),
                Field.select(
                    "language", L("Sprache", "Language"),
                    [{"value": "de-DE", "label": "Deutsch"}, {"value": "en-US", "label": "English"}],
                    value=str(lang), reload_on_change=True,
                ),
            ],
        )

    @settings_panel.on_submit
    async def _save_settings(self, ctx, data):
        conf = self.config.guild(ctx.guild)
        await conf.enabled.set(bool(data.get("enabled")))
        await conf.dm_user.set(bool(data.get("dm_user")))
        ch = str(data.get("log_channel") or "").strip()
        await (conf.log_channel.set(int(ch)) if ch.isdigit() else conf.log_channel.clear())
        raw = str(data.get("reasons") or "")
        reasons = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        await conf.reasons.set(reasons)
        lang = str(data.get("language", "en-US")).strip() or "en-US"
        await conf.language.set(lang)
        return SubmitResult.ok(tr_lang(lang, "Gespeichert.", "Saved."))
