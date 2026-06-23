"""WebServerStats – collects server statistics for the DKS web dashboard.

Data is stored in daily buckets (and for status/activity in hourly samples) in the
Red config and queried by the WebDashboard gateway via public read methods
(``stats_*``). The chart rendering happens in the web app.

Notes:
- Bots are ignored for messages/voice/activity (user type = users).
- Status/activity require the presence and member intents for complete data.
- Old buckets are removed automatically after RETENTION_DAYS.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.dks.web_serverstats")

RETENTION_DAYS = 400          # how long daily buckets are kept
SAMPLE_MINUTES = 30           # interval of the status/activity snapshots
STATUS_RETENTION = 60 * 24 * 60 // SAMPLE_MINUTES  # ~60 days of status samples


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _daykey(dt: Optional[datetime] = None) -> str:
    return (dt or _utcnow()).strftime("%Y-%m-%d")


class WebServerStats(commands.Cog):
    """Server statistics for the DKS web dashboard."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x57_57_53_01, force_registration=True)
        self.config.register_guild(
            enabled=True,
            days={},            # {daykey: {messages, joins, leaves, members, voice_minutes}}
            msg_channels={},     # {daykey: {channel_id: count}}
            msg_members={},      # {daykey: {member_id: count}}
            voice_channels={},   # {daykey: {channel_id: minutes}}
            voice_members={},    # {daykey: {member_id: minutes}}
            status_samples=[],   # [{"t": iso, "on": int, "idle": int, "dnd": int, "off": int}]
            activity={},         # {daykey: {game_name: minutes}}
            invites={},          # {code: {"uses": int, "inviter_id": int}}
            invite_daily={},     # {daykey: {code: joins}}
            invite_logs=[],      # [{"date","user_id","username","code"}]
            invite_members={},   # {member_id: count}  (joined members per inviter member)
            commands={},         # {daykey: {command_name: count}} – command usage
            command_errors={},   # {daykey: {command_name: count}} – errors per command
        )
        # Running voice sessions: {(guild_id, member_id): (channel_id, start_dt)}
        self._voice: Dict[Tuple[int, int], Tuple[int, datetime]] = {}
        # PERFORMANCE: messages are counted in-memory and written only periodically
        # (instead of 3 config writes per message).
        # {(guild_id, daykey): {"messages": int, "channels": {cid: int}, "members": {mid: int}}}
        self._msg_buf: Dict[Tuple[int, str], Dict[str, Any]] = {}
        # Command usage: {(guild_id, daykey): {"cmds": {name: n}, "errs": {name: n}}}
        self._cmd_buf: Dict[Tuple[int, str], Dict[str, Any]] = {}
        self._enabled_cache: Dict[int, bool] = {}
        self._snapshot_loop.start()
        self._flush_loop.start()

    def cog_unload(self) -> None:
        self._snapshot_loop.cancel()
        self._flush_loop.cancel()
        # Write out buffered counters + open voice sessions (best effort).
        try:
            asyncio.create_task(self._final_flush())
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Write helpers
    # ------------------------------------------------------------------ #
    async def _bump_day(self, guild: discord.Guild, field: str, amount: float = 1) -> None:
        key = _daykey()
        async with self.config.guild(guild).days() as days:
            d = days.get(key)
            if not isinstance(d, dict):
                d = {}
            d[field] = d.get(field, 0) + amount
            days[key] = d

    async def _bump_nested(self, guild: discord.Guild, group: str, sub: str, amount: float = 1) -> None:
        key = _daykey()
        async with getattr(self.config.guild(guild), group)() as data:
            day = data.get(key)
            if not isinstance(day, dict):
                day = {}
            day[sub] = day.get(sub, 0) + amount
            data[key] = day

    # ------------------------------------------------------------------ #
    # Listener: messages
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        gid = message.guild.id
        # Enabled status from the cache (no config read on the hot path).
        if not self._enabled_cache.get(gid, True):
            return
        try:
            entry = self._msg_buf.setdefault(
                (gid, _daykey()), {"messages": 0, "channels": {}, "members": {}}
            )
            entry["messages"] += 1
            ch_id = getattr(message.channel, "id", None)
            if ch_id:
                cid = str(ch_id)
                entry["channels"][cid] = entry["channels"].get(cid, 0) + 1
            aid = str(message.author.id)
            entry["members"][aid] = entry["members"].get(aid, 0) + 1
        except Exception:
            log.debug("on_message buffer failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Listener: command usage (in-memory, bundled with the message flush)
    # ------------------------------------------------------------------ #
    def _cmd_bump(self, guild, name: str, field: str) -> None:
        if guild is None or not name:
            return
        if not self._enabled_cache.get(guild.id, True):
            return
        entry = self._cmd_buf.setdefault((guild.id, _daykey()), {"cmds": {}, "errs": {}})
        bucket = entry["cmds"] if field == "cmds" else entry["errs"]
        bucket[name] = bucket.get(name, 0) + 1

    @commands.Cog.listener()
    async def on_command_completion(self, ctx) -> None:
        try:
            if ctx.guild is not None and ctx.command is not None:
                self._cmd_bump(ctx.guild, ctx.command.qualified_name, "cmds")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error) -> None:
        try:
            if ctx.guild is not None and ctx.command is not None:
                self._cmd_bump(ctx.guild, ctx.command.qualified_name, "errs")
        except Exception:
            pass

    async def _flush(self) -> None:
        """Writes buffered message and command counters to the config in a batch."""
        if not self._msg_buf and not self._cmd_buf:
            return
        buf = self._msg_buf
        self._msg_buf = {}
        by_guild: Dict[int, list] = {}
        for (gid, dk), e in buf.items():
            by_guild.setdefault(gid, []).append((dk, e))
        for gid, entries in by_guild.items():
            guild = self.bot.get_guild(gid)
            if guild is None:
                continue
            try:
                self._enabled_cache[gid] = bool(await self.config.guild(guild).enabled())
            except Exception:
                pass
            try:
                async with self.config.guild(guild).days() as days:
                    for dk, e in entries:
                        d = days.get(dk) if isinstance(days.get(dk), dict) else {}
                        d["messages"] = d.get("messages", 0) + e["messages"]
                        days[dk] = d
                async with self.config.guild(guild).msg_channels() as mc:
                    for dk, e in entries:
                        day = mc.get(dk) if isinstance(mc.get(dk), dict) else {}
                        for cid, n in e["channels"].items():
                            day[cid] = day.get(cid, 0) + n
                        mc[dk] = day
                async with self.config.guild(guild).msg_members() as mm:
                    for dk, e in entries:
                        day = mm.get(dk) if isinstance(mm.get(dk), dict) else {}
                        for mid, n in e["members"].items():
                            day[mid] = day.get(mid, 0) + n
                        mm[dk] = day
            except Exception:
                log.debug("flush failed for guild %s", gid, exc_info=True)

        # Batch command counters (separate buffer; a guild can have commands without messages).
        if self._cmd_buf:
            cbuf = self._cmd_buf
            self._cmd_buf = {}
            by_g: Dict[int, list] = {}
            for (gid, dk), e in cbuf.items():
                by_g.setdefault(gid, []).append((dk, e))
            for gid, entries in by_g.items():
                guild = self.bot.get_guild(gid)
                if guild is None:
                    continue
                try:
                    async with self.config.guild(guild).commands() as cmds:
                        for dk, e in entries:
                            day = cmds.get(dk) if isinstance(cmds.get(dk), dict) else {}
                            for nm, n in e["cmds"].items():
                                day[nm] = day.get(nm, 0) + n
                            cmds[dk] = day
                    async with self.config.guild(guild).command_errors() as errs:
                        for dk, e in entries:
                            day = errs.get(dk) if isinstance(errs.get(dk), dict) else {}
                            for nm, n in e["errs"].items():
                                day[nm] = day.get(nm, 0) + n
                            errs[dk] = day
                except Exception:
                    log.debug("cmd flush failed for guild %s", gid, exc_info=True)

    async def _final_flush(self) -> None:
        try:
            await self._flush()
        except Exception:
            pass
        for key in list(self._voice.keys()):
            gid, mid = key
            guild = self.bot.get_guild(gid)
            if guild is not None:
                try:
                    await self._end_voice_session(guild, mid, key)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # Listener: members
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        if not await self.config.guild(member.guild).enabled():
            return
        try:
            await self._bump_day(member.guild, "joins")
            await self._track_invite_use(member)
        except Exception:
            log.debug("on_member_join stats failed", exc_info=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        if not await self.config.guild(member.guild).enabled():
            return
        try:
            await self._bump_day(member.guild, "leaves")
        except Exception:
            log.debug("on_member_remove stats failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Listener: voice
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.bot or member.guild is None:
            return
        if not await self.config.guild(member.guild).enabled():
            return
        key = (member.guild.id, member.id)
        try:
            before_ch = before.channel.id if before.channel else None
            after_ch = after.channel.id if after.channel else None
            if before_ch == after_ch:
                return
            # End the old session + record it.
            if before_ch is not None and key in self._voice:
                await self._end_voice_session(member.guild, member.id, key)
            # Start the new session.
            if after_ch is not None:
                self._voice[key] = (after_ch, _utcnow())
        except Exception:
            log.debug("voice stats failed", exc_info=True)

    async def _end_voice_session(self, guild: discord.Guild, member_id: int, key) -> None:
        ch_id, start = self._voice.pop(key, (None, None))
        if ch_id is None or start is None:
            return
        minutes = max(0.0, (_utcnow() - start).total_seconds() / 60.0)
        if minutes <= 0:
            return
        await self._bump_day(guild, "voice_minutes", minutes)
        await self._bump_nested(guild, "voice_channels", str(ch_id), minutes)
        await self._bump_nested(guild, "voice_members", str(member_id), minutes)

    # ------------------------------------------------------------------ #
    # Listener: invites
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild is None:
            return
        try:
            async with self.config.guild(invite.guild).invites() as inv:
                inv[invite.code] = {
                    "uses": invite.uses or 0,
                    "inviter_id": invite.inviter.id if invite.inviter else 0,
                }
        except Exception:
            log.debug("invite_create stats failed", exc_info=True)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        # Remove deleted invites from the store so it does not grow unbounded with
        # stale codes (the live comparison in _track_invite_use uses guild.invites()
        # anyway, so dropping a gone code does not lose any attribution).
        if invite.guild is None:
            return
        try:
            async with self.config.guild(invite.guild).invites() as inv:
                inv.pop(invite.code, None)
        except Exception:
            log.debug("invite_delete cleanup failed", exc_info=True)

    async def _track_invite_use(self, member: discord.Member) -> None:
        """Compares stored invite uses with the current ones to find the code that was used."""
        guild = member.guild
        try:
            current = await guild.invites()
        except Exception:
            return
        stored = await self.config.guild(guild).invites()
        used_code = None
        inviter_id = 0
        for inv in current:
            old = stored.get(inv.code, {}) if isinstance(stored, dict) else {}
            if (inv.uses or 0) > int(old.get("uses", 0)):
                used_code = inv.code
                inviter_id = inv.inviter.id if inv.inviter else 0
                break
        # Update the store.
        async with self.config.guild(guild).invites() as inv_store:
            for inv in current:
                inv_store[inv.code] = {
                    "uses": inv.uses or 0,
                    "inviter_id": inv.inviter.id if inv.inviter else 0,
                }
        if not used_code:
            return
        key = _daykey()
        async with self.config.guild(guild).invite_daily() as daily:
            day = daily.get(key) if isinstance(daily.get(key), dict) else {}
            day[used_code] = day.get(used_code, 0) + 1
            daily[key] = day
        async with self.config.guild(guild).invite_logs() as logs:
            logs.append({
                "date": _utcnow().isoformat(),
                "user_id": member.id,
                "username": member.name,
                "code": used_code,
            })
            del logs[:-500]  # keep only the last 500
        if inviter_id:
            async with self.config.guild(guild).invite_members() as im:
                im[str(inviter_id)] = im.get(str(inviter_id), 0) + 1

    # ------------------------------------------------------------------ #
    # Periodic snapshot: member count, status, activity
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            try:
                enabled = bool(await self.config.guild(guild).enabled())
                self._enabled_cache[guild.id] = enabled
                if not enabled:
                    continue
                # Populate the invite cache initially.
                try:
                    current = await guild.invites()
                    async with self.config.guild(guild).invites() as inv_store:
                        for inv in current:
                            inv_store[inv.code] = {
                                "uses": inv.uses or 0,
                                "inviter_id": inv.inviter.id if inv.inviter else 0,
                            }
                except Exception:
                    pass
                # Re-capture running voice sessions after a (re)start so that counting
                # continues after a reload and leave events do not run into nothing.
                now = _utcnow()
                for vc in guild.voice_channels:
                    for m in vc.members:
                        if not m.bot:
                            self._voice.setdefault((guild.id, m.id), (vc.id, now))
            except Exception:
                continue

    @commands.Cog.listener()
    async def on_cog_add(self, cog: commands.Cog) -> None:  # noqa: D401
        pass

    async def _do_snapshot(self) -> None:
        for guild in list(self.bot.guilds):
            try:
                enabled = bool(await self.config.guild(guild).enabled())
                self._enabled_cache[guild.id] = enabled
                if not enabled:
                    continue
                # Member count (last value of the day).
                await self._set_day(guild, "members", guild.member_count or 0)
                # Status count.
                on = idle = dnd = off = 0
                games: Dict[str, int] = defaultdict(int)
                for m in guild.members:
                    if m.bot:
                        continue
                    st = getattr(m, "status", discord.Status.offline)
                    if st == discord.Status.online:
                        on += 1
                    elif st == discord.Status.idle:
                        idle += 1
                    elif st == discord.Status.dnd:
                        dnd += 1
                    else:
                        off += 1
                    for act in getattr(m, "activities", []) or []:
                        if isinstance(act, discord.Game) or getattr(act, "type", None) == discord.ActivityType.playing:
                            name = getattr(act, "name", None)
                            if name:
                                games[name] += 1
                async with self.config.guild(guild).status_samples() as samples:
                    samples.append({
                        "t": _utcnow().isoformat(), "on": on, "idle": idle, "dnd": dnd, "off": off,
                    })
                    del samples[:-STATUS_RETENTION]
                if games:
                    key = _daykey()
                    async with self.config.guild(guild).activity() as act_store:
                        day = act_store.get(key) if isinstance(act_store.get(key), dict) else {}
                        for name, count in games.items():
                            # Each snapshot ≈ SAMPLE_MINUTES of play time per playing member.
                            day[name] = day.get(name, 0) + count * SAMPLE_MINUTES
                        act_store[key] = day
                await self._prune(guild)
            except Exception:
                log.debug("snapshot failed for guild %s", guild.id, exc_info=True)

    async def _set_day(self, guild: discord.Guild, field: str, value: float) -> None:
        key = _daykey()
        async with self.config.guild(guild).days() as days:
            d = days.get(key) if isinstance(days.get(key), dict) else {}
            d[field] = value
            days[key] = d

    async def _prune(self, guild: discord.Guild) -> None:
        cutoff = _daykey(_utcnow() - timedelta(days=RETENTION_DAYS))
        for group in ("days", "msg_channels", "msg_members", "voice_channels", "voice_members",
                      "activity", "invite_daily", "commands", "command_errors"):
            async with getattr(self.config.guild(guild), group)() as data:
                for k in [k for k in data.keys() if k < cutoff]:
                    data.pop(k, None)

    @tasks.loop(minutes=SAMPLE_MINUTES)
    async def _snapshot_loop(self) -> None:
        await self._do_snapshot()

    @_snapshot_loop.before_loop
    async def _before_snapshot(self) -> None:
        await self.bot.wait_until_red_ready()

    @tasks.loop(seconds=60)
    async def _flush_loop(self) -> None:
        try:
            await self._flush()
        except Exception:
            log.debug("flush loop failed", exc_info=True)
        try:
            await self._flush_voice()
        except Exception:
            log.debug("voice tick failed", exc_info=True)

    async def _flush_voice(self) -> None:
        """Credit the elapsed time of OPEN voice sessions incrementally and advance
        their start. Without this, a user's voice time only appears AFTER they leave
        (the session is credited on disconnect) – so people currently in voice would
        be invisible in the stats. Ticking every 60 s makes ongoing sessions show up
        live and also keeps day boundaries accurate (minutes land on the day they
        actually happened)."""
        now = _utcnow()
        for key in list(self._voice.keys()):
            ch_id, start = self._voice.get(key, (None, None))
            if ch_id is None or start is None:
                continue
            minutes = (now - start).total_seconds() / 60.0
            if minutes <= 0:
                continue
            gid, mid = key
            guild = self.bot.get_guild(gid)
            if guild is None:
                continue
            # Advance the session start first so we never double-count this slice.
            self._voice[key] = (ch_id, now)
            try:
                await self._bump_day(guild, "voice_minutes", minutes)
                await self._bump_nested(guild, "voice_channels", str(ch_id), minutes)
                await self._bump_nested(guild, "voice_members", str(mid), minutes)
            except Exception:
                log.debug("voice tick failed for %s", key, exc_info=True)

    @_flush_loop.before_loop
    async def _before_flush(self) -> None:
        await self.bot.wait_until_red_ready()

    # ================================================================== #
    # Read API (called by the WebDashboard gateway)
    # ================================================================== #
    def _range_keys(self, days: int) -> List[str]:
        days = max(1, min(int(days or 30), RETENTION_DAYS))
        today = _utcnow().date()
        return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]

    def _top(self, guild: discord.Guild, totals: Dict[str, float], kind: str, limit: int = 10) -> List[Dict[str, Any]]:
        items = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
        out = []
        for id_str, val in items:
            name = str(id_str)
            try:
                if kind == "member":
                    m = guild.get_member(int(id_str))
                    name = m.display_name if m else str(id_str)
                else:
                    c = guild.get_channel(int(id_str))
                    name = c.name if c else str(id_str)
            except Exception:
                name = str(id_str)
            out.append({"id": str(id_str), "name": name,
                        "value": round(val, 2) if isinstance(val, float) else val})
        return out

    async def stats_overview(self, guild: discord.Guild, days: int = 30) -> Dict[str, Any]:
        keys = self._range_keys(days)
        daysd = await self.config.guild(guild).days()
        daysd = daysd if isinstance(daysd, dict) else {}

        def day(k):
            d = daysd.get(k, {})
            return d if isinstance(d, dict) else {}

        members = [day(k).get("members") for k in keys]
        joins = [int(day(k).get("joins", 0)) for k in keys]
        leaves = [int(day(k).get("leaves", 0)) for k in keys]
        last7 = keys[-7:]
        return {
            "labels": keys,
            "members": members,
            "joins": joins,
            "leaves": leaves,
            "kpi": {
                "members": guild.member_count or 0,
                "joins_7d": sum(int(day(k).get("joins", 0)) for k in last7),
                "leaves_7d": sum(int(day(k).get("leaves", 0)) for k in last7),
                "messages_7d": sum(int(day(k).get("messages", 0)) for k in last7),
                "voice_hours_7d": round(sum(float(day(k).get("voice_minutes", 0)) for k in last7) / 60.0, 1),
            },
        }

    async def stats_messages(self, guild: discord.Guild, days: int = 30) -> Dict[str, Any]:
        keys = self._range_keys(days)
        daysd = await self.config.guild(guild).days()
        ch = await self.config.guild(guild).msg_channels()
        mem = await self.config.guild(guild).msg_members()
        series = [int((daysd.get(k, {}) or {}).get("messages", 0)) for k in keys]
        ch_tot: Dict[str, float] = defaultdict(int)
        mem_tot: Dict[str, float] = defaultdict(int)
        uniq_ch, uniq_mem = set(), set()
        for k in keys:
            for cid, c in (ch.get(k, {}) or {}).items():
                ch_tot[cid] += c
                uniq_ch.add(cid)
            for mid, c in (mem.get(k, {}) or {}).items():
                mem_tot[mid] += c
                uniq_mem.add(mid)
        return {
            "labels": keys, "values": series, "total": sum(series),
            "unique_members": len(uniq_mem), "unique_channels": len(uniq_ch),
            "top_members": self._top(guild, mem_tot, "member"),
            "top_channels": self._top(guild, ch_tot, "channel"),
        }

    async def stats_voice(self, guild: discord.Guild, days: int = 30) -> Dict[str, Any]:
        keys = self._range_keys(days)
        daysd = await self.config.guild(guild).days()
        ch = await self.config.guild(guild).voice_channels()
        mem = await self.config.guild(guild).voice_members()
        series = [round(float((daysd.get(k, {}) or {}).get("voice_minutes", 0)) / 60.0, 2) for k in keys]
        ch_tot: Dict[str, float] = defaultdict(float)
        mem_tot: Dict[str, float] = defaultdict(float)
        uniq_ch, uniq_mem = set(), set()
        for k in keys:
            for cid, c in (ch.get(k, {}) or {}).items():
                ch_tot[cid] += c / 60.0
                uniq_ch.add(cid)
            for mid, c in (mem.get(k, {}) or {}).items():
                mem_tot[mid] += c / 60.0
                uniq_mem.add(mid)
        return {
            "labels": keys, "values": series, "total": round(sum(series), 2),
            "unique_members": len(uniq_mem), "unique_channels": len(uniq_ch),
            "top_members": self._top(guild, mem_tot, "member"),
            "top_channels": self._top(guild, ch_tot, "channel"),
        }

    async def stats_status(self, guild: discord.Guild, days: int = 14) -> Dict[str, Any]:
        cutoff = (_utcnow() - timedelta(days=max(1, int(days or 14)))).isoformat()
        samples = await self.config.guild(guild).status_samples()
        out = [s for s in (samples or []) if str(s.get("t", "")) >= cutoff]
        return {"samples": out}

    async def stats_invites(self, guild: discord.Guild, days: int = 14) -> Dict[str, Any]:
        keys = self._range_keys(days)
        daily = await self.config.guild(guild).invite_daily()
        logs = await self.config.guild(guild).invite_logs()
        inv_members = await self.config.guild(guild).invite_members()
        codes = set()
        for k in keys:
            for code in (daily.get(k, {}) or {}).keys():
                codes.add(code)
        series = {code: [int((daily.get(k, {}) or {}).get(code, 0)) for k in keys] for code in codes}
        top = sorted(((code, sum(series[code])) for code in codes), key=lambda x: x[1], reverse=True)[:10]
        return {
            "labels": keys,
            "series": series,
            "top_invites": [{"code": c, "count": n} for c, n in top],
            "recent_logs": list(reversed((logs or [])[-25:])),
            "top_members": self._top(guild, {k: v for k, v in (inv_members or {}).items()}, "member"),
        }

    async def stats_activity(self, guild: discord.Guild, days: int = 30) -> Dict[str, Any]:
        keys = self._range_keys(days)
        act = await self.config.guild(guild).activity()
        tot: Dict[str, float] = defaultdict(float)
        for k in keys:
            for name, mins in (act.get(k, {}) or {}).items():
                tot[name] += mins
        top = sorted(tot.items(), key=lambda x: x[1], reverse=True)[:15]
        return {"top_games": [{"name": n, "minutes": round(m)} for n, m in top]}

    async def _entity_options(self, guild: discord.Guild, group: str, kind: str) -> List[Dict[str, str]]:
        data = await getattr(self.config.guild(guild), group)()
        tot: Dict[str, float] = defaultdict(float)
        for day in (data or {}).values():
            for _id, c in (day or {}).items():
                tot[_id] += c
        return [{"id": e["id"], "name": e["name"]} for e in self._top(guild, tot, kind, limit=200)]

    async def stats_commands(self, guild: discord.Guild, days: int = 30) -> Dict[str, Any]:
        keys = self._range_keys(days)
        cmds = await self.config.guild(guild).commands()
        errs = await self.config.guild(guild).command_errors()
        cmds = cmds if isinstance(cmds, dict) else {}
        errs = errs if isinstance(errs, dict) else {}
        series = [sum(int(v) for v in (cmds.get(k, {}) or {}).values()) for k in keys]
        tot: Dict[str, int] = defaultdict(int)
        etot: Dict[str, int] = defaultdict(int)
        for k in keys:
            for nm, n in (cmds.get(k, {}) or {}).items():
                tot[nm] += int(n)
            for nm, n in (errs.get(k, {}) or {}).items():
                etot[nm] += int(n)
        top = sorted(tot.items(), key=lambda x: x[1], reverse=True)[:20]
        return {
            "labels": keys,
            "values": series,
            "total": sum(series),
            "total_errors": sum(etot.values()),
            "unique_commands": len(tot),
            "top_commands": [
                {"name": nm, "count": c, "errors": int(etot.get(nm, 0))} for nm, c in top
            ],
        }

    async def stats_member_drilldown(self, guild: discord.Guild, member_id: int, days: int = 30) -> Dict[str, Any]:
        keys = self._range_keys(days)
        mem = await self.config.guild(guild).msg_members()
        vmem = await self.config.guild(guild).voice_members()
        options = await self._entity_options(guild, "msg_members", "member")
        if not member_id and options:
            member_id = int(options[0]["id"])
        msgs = [int((mem.get(k, {}) or {}).get(str(member_id), 0)) for k in keys]
        voice = [round(float((vmem.get(k, {}) or {}).get(str(member_id), 0)) / 60.0, 2) for k in keys]
        m = guild.get_member(int(member_id)) if member_id else None
        return {
            "labels": keys, "messages": msgs, "voice_hours": voice,
            "name": (m.display_name if m else str(member_id)),
            "member_id": str(member_id), "options": options,
        }

    async def stats_channel_drilldown(self, guild: discord.Guild, channel_id: int, days: int = 30) -> Dict[str, Any]:
        keys = self._range_keys(days)
        ch = await self.config.guild(guild).msg_channels()
        vch = await self.config.guild(guild).voice_channels()
        options = await self._entity_options(guild, "msg_channels", "channel")
        if not channel_id and options:
            channel_id = int(options[0]["id"])
        msgs = [int((ch.get(k, {}) or {}).get(str(channel_id), 0)) for k in keys]
        voice = [round(float((vch.get(k, {}) or {}).get(str(channel_id), 0)) / 60.0, 2) for k in keys]
        c = guild.get_channel(int(channel_id)) if channel_id else None
        return {
            "labels": keys, "messages": msgs, "voice_hours": voice,
            "name": (c.name if c else str(channel_id)),
            "channel_id": str(channel_id), "options": options,
        }
