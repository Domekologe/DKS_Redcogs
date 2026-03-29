"""Ephemeral UI for member ready_times (WoW-Guild cog config)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord

if TYPE_CHECKING:
    from .wowguild_automation import WowGuildAutomation

DAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_LABEL_DE = {
    "monday": "Montag",
    "tuesday": "Dienstag",
    "wednesday": "Mittwoch",
    "thursday": "Donnerstag",
    "friday": "Freitag",
    "saturday": "Samstag",
    "sunday": "Sonntag",
}
TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")


def _default_week() -> Dict[str, Dict[str, Any]]:
    return {k: {"can": False, "start": None, "end": None} for k in DAY_KEYS}


def _merge_ready_times(raw: Any) -> Dict[str, Dict[str, Any]]:
    base = _default_week()
    if not isinstance(raw, dict):
        return base
    for k in DAY_KEYS:
        cell = raw.get(k)
        if not isinstance(cell, dict):
            continue
        can = bool(cell.get("can"))
        start = cell.get("start")
        end = cell.get("end")
        if start is not None:
            start = str(start).strip() or None
        if end is not None:
            end = str(end).strip() or None
        base[k] = {"can": can, "start": start, "end": end}
    return base


def _norm_time(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = str(s).strip()
    if not t:
        return None
    if TIME_RE.match(t):
        return t
    return None


def format_day_line(key: str, cell: Dict[str, Any]) -> str:
    label = DAY_LABEL_DE.get(key, key)
    if not cell.get("can"):
        return f"**{label}:** —"
    start, end = cell.get("start"), cell.get("end")
    if start and end:
        extra = " (+1)" if _hhmm_to_min(str(end)) < _hhmm_to_min(str(start)) else ""
        return f"**{label}:** {start} – {end}{extra}"
    if start:
        return f"**{label}:** ab {start}"
    if end:
        return f"**{label}:** bis {end}"
    return f"**{label}:** (aktiv, keine Zeiten)"


def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def format_member_ready_times_block(raw: Any) -> str:
    data = _merge_ready_times(raw)
    lines = [format_day_line(k, data[k]) for k in DAY_KEYS]
    return "\n".join(lines)


def member_marked_any_day(raw: Any) -> bool:
    m = _merge_ready_times(raw)
    return any(bool(m[k].get("can")) for k in DAY_KEYS)


class ReadyDayModal(discord.ui.Modal):
    active = discord.ui.TextInput(
        label="Aktiv? (ja/nein)",
        placeholder="ja",
        max_length=4,
        required=True,
    )
    start = discord.ui.TextInput(
        label="Von (HH:MM, leer = egal)",
        placeholder="19:00",
        max_length=8,
        required=False,
    )
    end = discord.ui.TextInput(
        label="Bis (HH:MM, leer = egal)",
        placeholder="23:00",
        max_length=8,
        required=False,
    )

    def __init__(
        self,
        cog: "WowGuildAutomation",
        member: discord.Member,
        day_key: str,
    ) -> None:
        label = DAY_LABEL_DE.get(day_key, day_key)
        super().__init__(title=f"{label} — Bereitschaft")
        self.cog = cog
        self.member = member
        self.day_key = day_key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für den Besitzer.", ephemeral=True)
            return
        yn = str(self.active.value).lower().strip()
        can = yn in ("ja", "yes", "y", "j", "1", "true", "on")
        st = _norm_time(str(self.start.value) if self.start.value else None)
        en = _norm_time(str(self.end.value) if self.end.value else None)
        raw = await self.cog.config.member(self.member).ready_times()
        data = _merge_ready_times(raw)
        data[self.day_key] = {"can": can, "start": st, "end": en}
        await self.cog.config.member(self.member).ready_times.set(data)
        label = DAY_LABEL_DE.get(self.day_key, self.day_key)
        await interaction.response.send_message(
            f"{label} gespeichert: `{format_day_line(self.day_key, data[self.day_key])}`",
            ephemeral=True,
        )


class MemberReadyTimesView(discord.ui.View):
    def __init__(self, cog: "WowGuildAutomation", member: discord.Member) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.member = member
        self._day_key = "monday"
        opts = [
            discord.SelectOption(label=DAY_LABEL_DE[k], value=k, default=(k == "monday"))
            for k in DAY_KEYS
        ]
        self.day_sel = discord.ui.Select(placeholder="Wochentag", options=opts, row=0)
        self.day_sel.callback = self._on_day
        self.add_item(self.day_sel)

    async def _on_day(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        self._day_key = str((interaction.data.get("values") or ["monday"])[0])
        await interaction.response.defer()

    @discord.ui.button(label="Gewählten Tag bearbeiten", style=discord.ButtonStyle.primary, row=1)
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        raw = await self.cog.config.member(self.member).ready_times()
        data = _merge_ready_times(raw)
        await interaction.response.send_modal(ReadyDayModal(self.cog, self.member, self._day_key))

    @discord.ui.button(label="Übersicht aktualisieren", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        raw = await self.cog.config.member(self.member).ready_times()
        block = format_member_ready_times_block(raw)
        await interaction.response.edit_message(content=f"**Deine Bereitschaftszeiten**\n\n{block}", view=self)


async def send_member_readytimes_panel(
    cog: "WowGuildAutomation",
    interaction: discord.Interaction,
    member: discord.Member,
) -> None:
    raw = await cog.config.member(member).ready_times()
    block = format_member_ready_times_block(raw)
    await interaction.response.send_message(
        f"**Bereitschaftszeiten** — {member.display_name}\n\n{block}",
        view=MemberReadyTimesView(cog, member),
        ephemeral=True,
    )
