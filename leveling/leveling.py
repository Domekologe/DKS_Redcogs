"""Leveling — XP / level system with rank cards, ranks and role rewards.

Opt-in per guild (disabled by default). Bilingual output (DE/EN). Almost
everything is configurable from the **web dashboard**:
  * enable, announce + channel, message template
  * **message XP** (min–max) and **voice XP** (per minute)
  * cooldown, **max level**, **XP curve** (base + factor)
  * **ranks** (level → role rewards) as a managed table (add/edit/delete)
  * a live **leaderboard** preview

Rank cards are rendered with Pillow when available, otherwise a clean embed.
"""
from __future__ import annotations

import asyncio
import io
import logging
import random
import time
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dks_dashboard import (
    Field,
    L,
    PanelSchema,
    SubmitResult,
    dashboard_list,
    dashboard_panel,
    register_dashboard,
    tr_lang,
    unregister_dashboard,
)

log = logging.getLogger("red.dks.leveling")


def xp_for_level(level: int, base: int = 100, factor: int = 5) -> int:
    """Total cumulative XP needed to reach ``level`` for a tunable curve.

    Per-level cost = ``base + factor * n²`` (n = 0-based level index).
    """
    total = 0
    for n in range(level):
        total += base + factor * (n ** 2)
    return total


def level_from_xp(xp: int, base: int = 100, factor: int = 5, max_level: int = 0) -> int:
    level = 0
    while xp >= xp_for_level(level + 1, base, factor):
        level += 1
        if max_level and level >= max_level:
            break
    return level


class Leveling(commands.Cog):
    """XP / leveling system with rank cards, ranks and role rewards."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x1E5E10, force_registration=True)
        self.config.register_guild(
            enabled=False,
            xp_min=15,
            xp_max=25,
            voice_xp=0,  # XP per minute in voice (0 = off)
            cooldown=60,
            announce=True,
            channel=None,
            message="🎉 {mention} reached level **{level}**!",
            level_roles={},  # {str(level): role_id}
            stack_roles=False,
            no_xp_channels=[],
            max_level=0,  # 0 = no cap
            curve_base=100,
            curve_factor=5,
            language="en-US",
        )
        self.config.register_member(xp=0, last_ts=0.0)
        self._voice_task: Optional[asyncio.Task] = None

    async def cog_load(self) -> None:
        register_dashboard(self)
        self._voice_task = asyncio.create_task(self._voice_loop())

    def cog_unload(self) -> None:
        unregister_dashboard(self)
        if self._voice_task:
            self._voice_task.cancel()

    @staticmethod
    def _t(lang: str, de: str, en: str) -> str:
        return de if str(lang).lower().startswith("de") else en

    async def _curve(self, guild):
        conf = self.config.guild(guild)
        return int(await conf.curve_base()), int(await conf.curve_factor()), int(await conf.max_level())

    # ------------------------------------------------------------------ #
    # XP awarding (shared by message + voice)
    # ------------------------------------------------------------------ #
    async def _award(self, guild, member, amount, announce_channel) -> None:
        if amount <= 0:
            return
        base, factor, maxl = await self._curve(guild)
        mconf = self.config.member(member)
        old_xp = await mconf.xp()
        new_xp = old_xp + amount
        await mconf.xp.set(new_xp)
        old_level = level_from_xp(old_xp, base, factor, maxl)
        new_level = level_from_xp(new_xp, base, factor, maxl)
        if new_level > old_level:
            await self._on_level_up(guild, member, announce_channel, new_level)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return
        if not isinstance(message.author, discord.Member):
            return
        guild, member = message.guild, message.author
        conf = self.config.guild(guild)
        if not await conf.enabled():
            return
        if message.channel.id in (await conf.no_xp_channels()):
            return
        now = time.time()
        mconf = self.config.member(member)
        if now - await mconf.last_ts() < int(await conf.cooldown()):
            return
        lo = int(await conf.xp_min())
        gain = random.randint(lo, max(lo, int(await conf.xp_max())))
        await mconf.last_ts.set(now)
        await self._award(guild, member, gain, message.channel)

    async def _voice_loop(self) -> None:
        await self.bot.wait_until_red_ready()
        while True:
            try:
                await self._voice_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Leveling voice tick failed")
            await asyncio.sleep(60)

    async def _voice_tick(self) -> None:
        guilds = await self.config.all_guilds()
        for gid, gconf in guilds.items():
            if not gconf.get("enabled"):
                continue
            voice_xp = int(gconf.get("voice_xp", 0) or 0)
            if voice_xp <= 0:
                continue
            guild = self.bot.get_guild(gid)
            if guild is None:
                continue
            for vc in guild.voice_channels:
                humans = [m for m in vc.members if not m.bot]
                if len(humans) < 2:  # don't grant XP for sitting alone
                    continue
                for m in humans:
                    vs = m.voice
                    if vs and (vs.self_deaf or vs.deaf):
                        continue
                    await self._award(guild, m, voice_xp, None)

    async def _on_level_up(self, guild, member, channel, level) -> None:
        conf = self.config.guild(guild)
        level_roles = await conf.level_roles()
        stack = await conf.stack_roles()
        if level_roles and guild.me.guild_permissions.manage_roles:
            try:
                reward = level_roles.get(str(level))
                if reward:
                    role = guild.get_role(reward)
                    if role and role not in member.roles:
                        await member.add_roles(role, reason="Level reward")
                if not stack:
                    for lvl_s, rid in level_roles.items():
                        if int(lvl_s) < level:
                            r = guild.get_role(rid)
                            if r and r in member.roles:
                                await member.remove_roles(r, reason="Level reward (replaced)")
            except discord.Forbidden:
                pass
        if not await conf.announce():
            return
        target_id = await conf.channel()
        target = guild.get_channel(target_id) if target_id else channel
        if target is None or not target.permissions_for(guild.me).send_messages:
            return
        template = await conf.message() or "🎉 {mention} reached level **{level}**!"
        text = (
            template.replace("{mention}", member.mention)
            .replace("{name}", member.display_name)
            .replace("{level}", str(level))
        )
        try:
            await target.send(text)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ #
    # Rank card
    # ------------------------------------------------------------------ #
    async def _render_card(self, member, rank, level, xp_have, xp_need) -> Optional[discord.File]:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return None
        try:
            url = str(member.display_avatar.replace(size=128, static_format="png").url)
            async with aiohttp.ClientSession() as s:
                async with s.get(url) as r:
                    avatar_bytes = await r.read()
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((128, 128))
            mask = Image.new("L", (128, 128), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 128, 128), fill=255)

            W, H = 800, 200
            card = Image.new("RGBA", (W, H), (32, 34, 37, 255))
            draw = ImageDraw.Draw(card)
            card.paste(avatar, (30, 36), mask)

            def font(size):
                for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"):
                    try:
                        return ImageFont.truetype(name, size)
                    except Exception:
                        continue
                return ImageFont.load_default()

            white, grey, accent = (255, 255, 255), (170, 174, 181), (88, 101, 242)
            draw.text((190, 40), member.display_name[:24], font=font(40), fill=white)
            draw.text((190, 92), f"Level {level}   ·   Rank #{rank}", font=font(26), fill=grey)
            bx, by, bw, bh = 190, 140, 560, 26
            draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=13, fill=(56, 58, 64, 255))
            frac = max(0.0, min(1.0, xp_have / xp_need)) if xp_need else 0.0
            if frac > 0:
                draw.rounded_rectangle((bx, by, bx + int(bw * frac), by + bh), radius=13, fill=accent)
            draw.text((bx, by - 30), f"{xp_have} / {xp_need} XP", font=font(20), fill=grey)

            buf = io.BytesIO()
            card.save(buf, "PNG")
            buf.seek(0)
            return discord.File(buf, filename="rank.png")
        except Exception:
            log.debug("rank card render failed", exc_info=True)
            return None

    # ------------------------------------------------------------------ #
    # User commands
    # ------------------------------------------------------------------ #
    @commands.hybrid_command(name="rank", aliases=["level"])
    @commands.guild_only()
    @app_commands.describe(member="Member to look up (default: you)")
    async def rank(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        """Show your (or someone's) rank card."""
        member = member or ctx.author
        conf = self.config.guild(ctx.guild)
        lang = await conf.language()
        if not await conf.enabled():
            await ctx.send(self._t(lang, "Leveling ist hier deaktiviert.", "Leveling is disabled here."))
            return
        base, factor, maxl = await self._curve(ctx.guild)
        xp = await self.config.member(member).xp()
        level = level_from_xp(xp, base, factor, maxl)
        cur = xp_for_level(level, base, factor)
        need = xp_for_level(level + 1, base, factor) - cur
        have = xp - cur
        members = await self.config.all_members(ctx.guild)
        ranking = sorted(members.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)
        rank = next((i + 1 for i, (mid, _) in enumerate(ranking) if mid == member.id), len(ranking))
        await ctx.typing()
        card = await self._render_card(member, rank, level, have, max(1, need))
        if card is not None:
            await ctx.send(file=card)
            return
        embed = discord.Embed(title=f"{member.display_name}", colour=await ctx.embed_colour())
        embed.add_field(name="Level", value=str(level))
        embed.add_field(name="Rank", value=f"#{rank}")
        embed.add_field(name="XP", value=f"{have} / {need}")
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="leaderboard", aliases=["levels", "top"])
    @commands.guild_only()
    async def leaderboard(self, ctx: commands.Context) -> None:
        """Show the top members by XP."""
        conf = self.config.guild(ctx.guild)
        lang = await conf.language()
        base, factor, maxl = await self._curve(ctx.guild)
        members = await self.config.all_members(ctx.guild)
        ranking = sorted(members.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)[:10]
        if not ranking:
            await ctx.send(self._t(lang, "Noch keine XP vergeben.", "No XP yet."))
            return
        lines = []
        for i, (mid, mconf) in enumerate(ranking, start=1):
            m = ctx.guild.get_member(mid)
            xp = mconf.get("xp", 0)
            lines.append(f"**{i}.** {m.display_name if m else mid} — Level {level_from_xp(xp, base, factor, maxl)} ({xp} XP)")
        await ctx.send(embed=discord.Embed(
            title=self._t(lang, "🏆 Bestenliste", "🏆 Leaderboard"),
            description="\n".join(lines),
            colour=await ctx.embed_colour(),
        ))

    # ------------------------------------------------------------------ #
    # Admin configuration
    # ------------------------------------------------------------------ #
    @commands.hybrid_group(name="xpset", aliases=["levelset"])
    @commands.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def xpset(self, ctx: commands.Context) -> None:
        """Configure the leveling module."""

    @xpset.command(name="enable")
    @app_commands.describe(on_off="Enable or disable leveling")
    async def xp_enable(self, ctx: commands.Context, on_off: bool) -> None:
        """Enable/disable leveling for this server."""
        lang = await self.config.guild(ctx.guild).language()
        await self.config.guild(ctx.guild).enabled.set(on_off)
        state = self._t(lang, "aktiviert" if on_off else "deaktiviert", "enabled" if on_off else "disabled")
        await ctx.send(self._t(lang, f"Leveling **{state}**.", f"Leveling **{state}**."))

    @xpset.command(name="cooldown")
    @app_commands.describe(seconds="Seconds between XP awards per member")
    async def xp_cooldown(self, ctx: commands.Context, seconds: int) -> None:
        """Set the per-member message XP cooldown (seconds)."""
        lang = await self.config.guild(ctx.guild).language()
        await self.config.guild(ctx.guild).cooldown.set(max(0, seconds))
        await ctx.send(self._t(lang, f"Cooldown: {max(0, seconds)}s", f"Cooldown: {max(0, seconds)}s"))

    @xpset.command(name="xprange")
    @app_commands.describe(minimum="Min XP per message", maximum="Max XP per message")
    async def xp_range(self, ctx: commands.Context, minimum: int, maximum: int) -> None:
        """Set the message XP range."""
        lang = await self.config.guild(ctx.guild).language()
        minimum = max(1, minimum)
        maximum = max(minimum, maximum)
        await self.config.guild(ctx.guild).xp_min.set(minimum)
        await self.config.guild(ctx.guild).xp_max.set(maximum)
        await ctx.send(self._t(lang, f"Nachrichten-XP: {minimum}–{maximum}", f"Message XP: {minimum}–{maximum}"))

    @xpset.command(name="voicexp")
    @app_commands.describe(per_minute="XP awarded per minute spent in a voice channel (0 = off)")
    async def xp_voice(self, ctx: commands.Context, per_minute: int) -> None:
        """Set the voice XP per minute (0 disables voice XP)."""
        lang = await self.config.guild(ctx.guild).language()
        await self.config.guild(ctx.guild).voice_xp.set(max(0, per_minute))
        await ctx.send(self._t(lang, f"Voice-XP/Min: {max(0, per_minute)}", f"Voice XP/min: {max(0, per_minute)}"))

    @xpset.command(name="maxlevel")
    @app_commands.describe(level="Maximum level (0 = no cap)")
    async def xp_maxlevel(self, ctx: commands.Context, level: int) -> None:
        """Set the maximum level (0 = unlimited)."""
        lang = await self.config.guild(ctx.guild).language()
        await self.config.guild(ctx.guild).max_level.set(max(0, level))
        await ctx.send(self._t(lang, f"Max. Level: {max(0, level) or '∞'}", f"Max level: {max(0, level) or '∞'}"))

    @xpset.command(name="curve")
    @app_commands.describe(base="Base XP per level", factor="Quadratic factor (steeper = harder)")
    async def xp_curve(self, ctx: commands.Context, base: int, factor: int) -> None:
        """Set the XP curve (cost per level = base + factor·n²)."""
        lang = await self.config.guild(ctx.guild).language()
        await self.config.guild(ctx.guild).curve_base.set(max(1, base))
        await self.config.guild(ctx.guild).curve_factor.set(max(0, factor))
        await ctx.send(self._t(lang, f"Kurve: base={max(1, base)}, factor={max(0, factor)}", f"Curve: base={max(1, base)}, factor={max(0, factor)}"))

    @xpset.command(name="announce")
    @app_commands.describe(channel="Level-up channel (leave empty = same channel as the message)")
    async def xp_announce(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """Set (or clear) the level-up announcement channel."""
        lang = await self.config.guild(ctx.guild).language()
        if channel is None:
            await self.config.guild(ctx.guild).channel.clear()
            await ctx.send(self._t(lang, "Level-Ups im jeweiligen Kanal.", "Level-ups in the message's channel."))
            return
        await self.config.guild(ctx.guild).channel.set(channel.id)
        await ctx.send(self._t(lang, f"Level-Up-Kanal: {channel.mention}", f"Level-up channel: {channel.mention}"))

    @xpset.command(name="levelrole")
    @app_commands.describe(level="Level number", role="Role to grant at that level (omit to remove)")
    async def xp_levelrole(self, ctx: commands.Context, level: int, role: Optional[discord.Role] = None) -> None:
        """Add or remove a level→role reward (rank)."""
        lang = await self.config.guild(ctx.guild).language()
        async with self.config.guild(ctx.guild).level_roles() as lr:
            if role is None:
                lr.pop(str(level), None)
                await ctx.send(self._t(lang, f"Rang für Level {level} entfernt.", f"Rank for level {level} removed."))
            else:
                lr[str(level)] = role.id
                await ctx.send(self._t(lang, f"Level {level} → {role.mention}", f"Level {level} → {role.mention}"))

    @xpset.command(name="noxp")
    @app_commands.describe(channel="Channel to toggle as no-XP")
    async def xp_noxp(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Toggle a channel where no XP is awarded."""
        lang = await self.config.guild(ctx.guild).language()
        async with self.config.guild(ctx.guild).no_xp_channels() as nx:
            if channel.id in nx:
                nx.remove(channel.id)
                await ctx.send(self._t(lang, f"{channel.mention} gibt wieder XP.", f"{channel.mention} grants XP again."))
            else:
                nx.append(channel.id)
                await ctx.send(self._t(lang, f"{channel.mention} ohne XP.", f"{channel.mention} is no-XP."))

    @xpset.command(name="language")
    @app_commands.describe(language="Output language: de-DE or en-US")
    async def xp_language(self, ctx: commands.Context, language: str) -> None:
        """Set the output language for this server."""
        language = "de-DE" if language.lower().startswith("de") else "en-US"
        await self.config.guild(ctx.guild).language.set(language)
        await ctx.send(self._t(language, "Sprache: Deutsch", "Language: English"))

    # ------------------------------------------------------------------ #
    # Dashboard: main settings panel
    # ------------------------------------------------------------------ #
    @dashboard_panel("leveling", L("Leveling", "Leveling"), mount="guild_settings", permission="guild_admin", order=40)
    async def settings_panel(self, ctx):
        conf = self.config.guild(ctx.guild)
        lang = await conf.language()
        base, factor, maxl = await self._curve(ctx.guild)
        members = await self.config.all_members(ctx.guild)
        top = sorted(members.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)[:5]
        board = "\n".join(
            f"{i}. {(ctx.guild.get_member(mid) or mid)} — L{level_from_xp(mc.get('xp', 0), base, factor, maxl)} ({mc.get('xp', 0)} XP)"
            for i, (mid, mc) in enumerate(top, start=1)
        ) or "—"
        return PanelSchema(
            description=tr_lang(
                lang,
                f"XP-/Level-System. Ränge verwaltest du im Tab 'Ränge'.\n\n**Bestenliste**\n{board}",
                f"XP / leveling system. Manage ranks in the 'Ranks' tab.\n\n**Leaderboard**\n{board}",
            ),
            fields=[
                Field.switch("enabled", L("Aktiviert", "Enabled"), value=bool(await conf.enabled())),
                Field.switch("announce", L("Level-Up ankündigen", "Announce level-ups"), value=bool(await conf.announce())),
                Field.channel("channel", L("Level-Up-Kanal", "Level-up channel"), value=str(await conf.channel() or "")),
                Field.number("cooldown", L("Cooldown (s)", "Cooldown (s)"), value=int(await conf.cooldown())),
                Field.number("xp_min", L("Nachrichten-XP min", "Message XP min"), value=int(await conf.xp_min())),
                Field.number("xp_max", L("Nachrichten-XP max", "Message XP max"), value=int(await conf.xp_max())),
                Field.number("voice_xp", L("Voice-XP / Minute (0 = aus)", "Voice XP / minute (0 = off)"), value=int(await conf.voice_xp())),
                Field.number("max_level", L("Max. Level (0 = ∞)", "Max level (0 = ∞)"), value=int(maxl)),
                Field.number("curve_base", L("XP-Kurve: Basis", "XP curve: base"), value=int(base)),
                Field.number("curve_factor", L("XP-Kurve: Faktor (n²)", "XP curve: factor (n²)"), value=int(factor)),
                Field.switch("stack_roles", L("Rang-Rollen stapeln", "Stack rank roles"), value=bool(await conf.stack_roles())),
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

        def _int(key, default):
            try:
                return int(data.get(key, default))
            except (TypeError, ValueError):
                return default

        await conf.enabled.set(bool(data.get("enabled")))
        await conf.announce.set(bool(data.get("announce")))
        await conf.stack_roles.set(bool(data.get("stack_roles")))
        ch = str(data.get("channel") or "").strip()
        await (conf.channel.set(int(ch)) if ch.isdigit() else conf.channel.clear())
        await conf.cooldown.set(max(0, _int("cooldown", 60)))
        mn = max(1, _int("xp_min", 15))
        mx = max(mn, _int("xp_max", 25))
        await conf.xp_min.set(mn)
        await conf.xp_max.set(mx)
        await conf.voice_xp.set(max(0, _int("voice_xp", 0)))
        await conf.max_level.set(max(0, _int("max_level", 0)))
        await conf.curve_base.set(max(1, _int("curve_base", 100)))
        await conf.curve_factor.set(max(0, _int("curve_factor", 5)))
        lang = str(data.get("language", "en-US")).strip() or "en-US"
        await conf.language.set(lang)
        return SubmitResult.ok(tr_lang(lang, "Gespeichert.", "Saved."))

    # ------------------------------------------------------------------ #
    # Dashboard: ranks (level → role) as a managed table
    # ------------------------------------------------------------------ #
    @dashboard_list(
        "levelroles", L("Ränge", "Ranks"), mount="guild_settings", permission="guild_admin", order=42,
        columns=[{"key": "level", "label": "Level"}, {"key": "role", "label": "Role"}],
        description=L("Level → Rolle. Neue Ränge im Tab 'Rang anlegen'.", "Level → role. Add new ranks in the 'Add rank' tab."),
    )
    async def ranks_list(self, ctx):
        lr = await self.config.guild(ctx.guild).level_roles()
        rows = []
        for lvl, rid in sorted(lr.items(), key=lambda kv: int(kv[0])):
            role = ctx.guild.get_role(rid)
            rows.append({"id": str(lvl), "cells": {"level": str(lvl), "role": role.name if role else str(rid)}})
        return rows

    @ranks_list.edit_form
    async def ranks_edit_form(self, ctx, item_id):
        lr = await self.config.guild(ctx.guild).level_roles()
        rid = lr.get(str(item_id))
        return PanelSchema(fields=[
            Field.number("level", L("Level", "Level"), value=int(item_id)),
            Field.role("role", L("Rolle", "Role"), value=str(rid or "")),
        ])

    @ranks_list.on_edit
    async def ranks_edit(self, ctx, item_id, data):
        lang = await self.config.guild(ctx.guild).language()
        role = str(data.get("role") or "").strip()
        try:
            new_level = int(data.get("level", item_id))
        except (TypeError, ValueError):
            new_level = int(item_id)
        async with self.config.guild(ctx.guild).level_roles() as lr:
            lr.pop(str(item_id), None)
            if role.isdigit() and new_level > 0:
                lr[str(new_level)] = int(role)
        return SubmitResult.ok(tr_lang(lang, "Rang gespeichert.", "Rank saved."))

    @ranks_list.on_delete
    async def ranks_delete(self, ctx, item_id):
        lang = await self.config.guild(ctx.guild).language()
        async with self.config.guild(ctx.guild).level_roles() as lr:
            lr.pop(str(item_id), None)
        return SubmitResult.ok(tr_lang(lang, "Rang gelöscht.", "Rank deleted."))

    @dashboard_panel("levelrole_add", L("Rang anlegen", "Add rank"), mount="guild_settings", permission="guild_admin", order=41)
    async def rank_add_panel(self, ctx):
        lang = await self.config.guild(ctx.guild).language()
        return PanelSchema(
            description=tr_lang(lang, "Neuen Rang (Level → Rolle) anlegen.", "Add a new rank (level → role)."),
            fields=[
                Field.number("level", L("Level", "Level"), value=5),
                Field.role("role", L("Rolle", "Role"), value=""),
            ],
        )

    @rank_add_panel.on_submit
    async def _rank_add(self, ctx, data):
        lang = await self.config.guild(ctx.guild).language()
        role = str(data.get("role") or "").strip()
        try:
            level = int(data.get("level", 0))
        except (TypeError, ValueError):
            level = 0
        if level <= 0 or not role.isdigit():
            return SubmitResult.fail(tr_lang(lang, "Level und Rolle erforderlich.", "Level and role required."))
        async with self.config.guild(ctx.guild).level_roles() as lr:
            lr[str(level)] = int(role)
        return SubmitResult.ok(tr_lang(lang, "Rang angelegt.", "Rank added."), reload=True)
