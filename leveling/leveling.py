"""Leveling — XP / level system with rank cards and role rewards.

Opt-in per guild (disabled by default). Bilingual output (DE/EN). Web dashboard
integration (enable, announce channel, language, cooldown, XP range) via the
resilient drop-in. Rank cards are rendered with Pillow when available, otherwise
a clean embed is shown instead.
"""
from __future__ import annotations

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
    dashboard_panel,
    register_dashboard,
    tr_lang,
    unregister_dashboard,
)

log = logging.getLogger("red.dks.leveling")


def xp_for_level(level: int) -> int:
    """Total cumulative XP required to reach ``level`` (MEE6-like curve)."""
    total = 0
    for n in range(level):
        total += 5 * (n ** 2) + 50 * n + 100
    return total


def level_from_xp(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


class Leveling(commands.Cog):
    """XP / leveling system with rank cards and role rewards."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x1E5E10, force_registration=True)
        self.config.register_guild(
            enabled=False,
            xp_min=15,
            xp_max=25,
            cooldown=60,
            announce=True,
            channel=None,  # level-up announce channel; None = same channel
            message="🎉 {mention} reached level **{level}**!",
            level_roles={},  # {str(level): role_id}
            stack_roles=False,
            no_xp_channels=[],
            language="en-US",
        )
        self.config.register_member(xp=0, last_ts=0.0)

    async def cog_load(self) -> None:
        register_dashboard(self)

    def cog_unload(self) -> None:
        unregister_dashboard(self)

    @staticmethod
    def _t(lang: str, de: str, en: str) -> str:
        return de if str(lang).lower().startswith("de") else en

    # ------------------------------------------------------------------ #
    # XP awarding
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return
        if isinstance(message.author, discord.Member) is False:
            return
        guild, member = message.guild, message.author
        conf = self.config.guild(guild)
        if not await conf.enabled():
            return
        if message.channel.id in (await conf.no_xp_channels()):
            return
        now = time.time()
        mconf = self.config.member(member)
        last = await mconf.last_ts()
        if now - last < int(await conf.cooldown()):
            return
        gain = random.randint(int(await conf.xp_min()), max(int(await conf.xp_min()), int(await conf.xp_max())))
        old_xp = await mconf.xp()
        new_xp = old_xp + gain
        old_level = level_from_xp(old_xp)
        new_level = level_from_xp(new_xp)
        await mconf.xp.set(new_xp)
        await mconf.last_ts.set(now)
        if new_level > old_level:
            await self._on_level_up(guild, member, message.channel, new_level)

    async def _on_level_up(self, guild, member, channel, level) -> None:
        conf = self.config.guild(guild)
        # Role rewards.
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
                    # Remove lower reward roles.
                    for lvl_s, rid in level_roles.items():
                        if int(lvl_s) < level:
                            r = guild.get_role(rid)
                            if r and r in member.roles:
                                await member.remove_roles(r, reason="Level reward (replaced)")
            except discord.Forbidden:
                pass
        # Announcement.
        if not await conf.announce():
            return
        lang = await conf.language()
        target_id = await conf.channel()
        target = guild.get_channel(target_id) if target_id else channel
        if target is None or not target.permissions_for(guild.me).send_messages:
            return
        template = await conf.message() or "🎉 {mention} reached level **{level}**!"
        text = template.replace("{mention}", member.mention).replace("{name}", member.display_name).replace("{level}", str(level))
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
            # progress bar
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
        lang = await self.config.guild(ctx.guild).language()
        if not await self.config.guild(ctx.guild).enabled():
            await ctx.send(self._t(lang, "Leveling ist hier deaktiviert.", "Leveling is disabled here."))
            return
        xp = await self.config.member(member).xp()
        level = level_from_xp(xp)
        base = xp_for_level(level)
        need = xp_for_level(level + 1) - base
        have = xp - base
        # Rank position.
        members = await self.config.all_members(ctx.guild)
        ranking = sorted(members.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)
        rank = next((i + 1 for i, (mid, _) in enumerate(ranking) if mid == member.id), len(ranking))
        await ctx.typing()
        card = await self._render_card(member, rank, level, have, need)
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
        lang = await self.config.guild(ctx.guild).language()
        members = await self.config.all_members(ctx.guild)
        ranking = sorted(members.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)[:10]
        if not ranking:
            await ctx.send(self._t(lang, "Noch keine XP vergeben.", "No XP yet."))
            return
        lines = []
        for i, (mid, mconf) in enumerate(ranking, start=1):
            m = ctx.guild.get_member(mid)
            xp = mconf.get("xp", 0)
            lines.append(f"**{i}.** {m.display_name if m else mid} — Level {level_from_xp(xp)} ({xp} XP)")
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
        """Set the per-member XP cooldown (seconds)."""
        lang = await self.config.guild(ctx.guild).language()
        await self.config.guild(ctx.guild).cooldown.set(max(0, seconds))
        await ctx.send(self._t(lang, f"Cooldown: {max(0, seconds)}s", f"Cooldown: {max(0, seconds)}s"))

    @xpset.command(name="xprange")
    @app_commands.describe(minimum="Min XP per message", maximum="Max XP per message")
    async def xp_range(self, ctx: commands.Context, minimum: int, maximum: int) -> None:
        """Set the XP range awarded per message."""
        lang = await self.config.guild(ctx.guild).language()
        minimum = max(1, minimum)
        maximum = max(minimum, maximum)
        await self.config.guild(ctx.guild).xp_min.set(minimum)
        await self.config.guild(ctx.guild).xp_max.set(maximum)
        await ctx.send(self._t(lang, f"XP pro Nachricht: {minimum}–{maximum}", f"XP per message: {minimum}–{maximum}"))

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
        """Add or remove a level→role reward."""
        lang = await self.config.guild(ctx.guild).language()
        async with self.config.guild(ctx.guild).level_roles() as lr:
            if role is None:
                lr.pop(str(level), None)
                await ctx.send(self._t(lang, f"Belohnung für Level {level} entfernt.", f"Reward for level {level} removed."))
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
    # Dashboard panel
    # ------------------------------------------------------------------ #
    @dashboard_panel("leveling", L("Leveling", "Leveling"), mount="guild_settings", permission="guild_admin", order=40)
    async def settings_panel(self, ctx):
        conf = self.config.guild(ctx.guild)
        lang = await conf.language()
        channels = [{"value": "", "label": "—"}] + [
            {"value": str(c.id), "label": f"#{c.name}"} for c in ctx.guild.text_channels
        ]
        return PanelSchema(
            description=tr_lang(lang, "XP-/Level-System für diesen Server.", "XP / leveling system for this server."),
            fields=[
                Field.switch("enabled", L("Aktiviert", "Enabled"), value=bool(await conf.enabled())),
                Field.switch("announce", L("Level-Up ankündigen", "Announce level-ups"), value=bool(await conf.announce())),
                Field.select("channel", L("Level-Up-Kanal", "Level-up channel"), channels, value=str(await conf.channel() or "")),
                Field.number("cooldown", L("Cooldown (s)", "Cooldown (s)"), value=int(await conf.cooldown())),
                Field.number("xp_min", L("XP min", "XP min"), value=int(await conf.xp_min())),
                Field.number("xp_max", L("XP max", "XP max"), value=int(await conf.xp_max())),
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
        await conf.announce.set(bool(data.get("announce")))
        ch = str(data.get("channel") or "").strip()
        await (conf.channel.set(int(ch)) if ch.isdigit() else conf.channel.clear())

        def _int(key, default):
            try:
                return int(data.get(key, default))
            except (TypeError, ValueError):
                return default

        await conf.cooldown.set(max(0, _int("cooldown", 60)))
        mn = max(1, _int("xp_min", 15))
        mx = max(mn, _int("xp_max", 25))
        await conf.xp_min.set(mn)
        await conf.xp_max.set(mx)
        lang = str(data.get("language", "en-US")).strip() or "en-US"
        await conf.language.set(lang)
        return SubmitResult.ok(tr_lang(lang, "Gespeichert.", "Saved."))
