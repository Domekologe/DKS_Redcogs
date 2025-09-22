# GuildTools ReadyTimes Cog — Slash-only, ephemeral interactions
# Author: Domekologe (per project context)
# Requires: Red-DiscordBot (v3.5+), discord.py 2.3+
# File path suggestion: guildtools/readytimes.py (inside your GuildTools repo/package)

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List, Literal

import discord
from discord import app_commands
from redbot.core import commands, Config
from redbot.core.bot import Red

WEEKDAYS = [
    ("monday", "Montag"),
    ("tuesday", "Dienstag"),
    ("wednesday", "Mittwoch"),
    ("thursday", "Donnerstag"),
    ("friday", "Freitag"),
    ("saturday", "Samstag"),
    ("sunday", "Sonntag"),
]

# Useful maps
DAY_KEY_TO_DE = {k: de for k, de in WEEKDAYS}
DAY_DE_TO_KEY = {de: k for k, de in WEEKDAYS}
DAY_ORDER = [k for k, _ in WEEKDAYS]

TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")  # 24h HH:MM

@dataclass
class DayAvailability:
    can: bool = False
    start: Optional[str] = None  # "HH:MM"
    end: Optional[str] = None    # "HH:MM"

    def as_tuple_minutes(self) -> Optional[Tuple[int, int]]:
        if not self.can or not self.start or not self.end:
            return None
        return (hhmm_to_min(self.start), hhmm_to_min(self.end))


def hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def min_to_hhmm(v: int) -> str:
    v = max(0, min(23 * 60 + 59, v))
    return f"{v // 60:02d}:{v % 60:02d}"


def parse_time_or_none(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    if TIME_RE.match(s):
        return s
    return None


def normalize_time_input(s: Optional[str]) -> Optional[str]:
    if s is None: return None
    s = str(s).strip()
    if not s: return None
    if TIME_RE.match(s):  # already HH:MM
        return s
    if s.isdigit():
        if len(s) <= 2:  # "22" -> 22:00
            h = int(s)
            if 0 <= h <= 23:
                return f"{h:02d}:00"
        elif len(s) == 3:  # "915" -> 09:15
            h, m = int(s[0]), int(s[1:])
        elif len(s) == 4:  # "2230" -> 22:30
            h, m = int(s[:2]), int(s[2:])
        else:
            return None
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    return None

def parse_time_or_none(s: Optional[str]) -> Optional[str]:
    return normalize_time_input(s)


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def format_range(start: Optional[str], end: Optional[str]) -> str:
    if start and end:
        return f"{start} - {end}"
    if start and not end:
        return f"Ab {start}"
    if end and not start:
        return f"Bis {end}"
    return "-"


def format_range_with_parens(start: Optional[str], end: Optional[str]) -> str:
    # For filtering displays where one side is missing
    if start and end:
        return f"{start} - {end}"
    if start and not end:
        return f"Beginn: {start} (Bis)"
    if end and not start:
        return f"(Ab) Ende: {end}"
    return "-"


class ReadyTimes(commands.Cog):
    """GuildTools Zusatz: Verfügbarkeiten pro Wochentag verwalten & abfragen (ephemeral)."""

    __author__ = "Domekologe"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xD0DE20251, force_registration=True)
        member_defaults = {
            day: {"can": False, "start": None, "end": None} for day, _ in WEEKDAYS
        }
        self.config.register_member(**member_defaults)

    # ------------------------------
    # Slash: /set-readytimes (ephemeral UI)
    # ------------------------------

    @app_commands.command(name="set-readytimes", description="Setze/verwalte deine Raid-Verfügbarkeiten privat.")
    async def set_readytimes(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, (discord.Member,)):
            return await interaction.response.send_message("Nur in einem Server benutzbar.", ephemeral=True)

        # Load current state
        member_cfg = await self.config.member(interaction.user).get_raw()
        avail_map: Dict[str, DayAvailability] = {
            day: DayAvailability(can=v["can"], start=v["start"], end=v["end"]) for day, v in member_cfg.items()
        }

        view = ReadyTimesView(self, interaction.user, avail_map)
        embed = await view.build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        try:
            original = await interaction.original_response()
            view.message_id = original.id
        except Exception:
            view.message_id = None
    # ------------------------------
    # Slash: /get-readytimes [day] [start] [end]
    # ------------------------------

    @app_commands.command(name="get-readytimes", description="Abfrage, wer wann kann (Antwort ist privat).")
    @app_commands.describe(day="Optional: Wochentag", start="Optional: Startzeit HH:MM", end="Optional: Endzeit HH:MM")
    async def get_readytimes(
        self,
        interaction: discord.Interaction,
        day: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ):
        if not interaction.guild:
            return await interaction.response.send_message("Nur in einem Server benutzbar.", ephemeral=True)

        start_t = parse_time_or_none(start)
        end_t   = parse_time_or_none(end)
        if start and not start_t:
            return await interaction.response.send_message("Ungültige Startzeit. Nutze HH:MM (24h).", ephemeral=True)
        if end and not end_t:
            return await interaction.response.send_message("Ungültige Endzeit. Nutze HH:MM (24h).", ephemeral=True)

        # Guild-Mitglieder (Bots raus)
        results = []
        for member in interaction.guild.members:
            if member.bot:
                continue
            data = await self.config.member(member).get_raw()
            results.append((member, data))

        # Helper: day normalisieren (Key wie "monday"); akzeptiere auch "Montag"
        day_key = None
        if day:
            d = day.strip().lower()
            # direkter key?
            if d in DAY_ORDER:
                day_key = d
            else:
                # versuche deutsches Label -> key
                de2key = {v.lower(): k for k, v in DAY_KEY_TO_DE.items()}
                if d in de2key:
                    day_key = de2key[d]
                else:
                    return await interaction.response.send_message("Unbekannter Wochentag.", ephemeral=True)

        # 1) Keine Args => Gesamtübersicht
        if not day_key and not start_t and not end_t:
            embed = discord.Embed(title="Gesamtübersicht Verfügbarkeiten", color=discord.Color.blurple())
            for key in DAY_ORDER:
                parts: List[str] = []
                for member, data in results:
                    info = data.get(key, {"can": False, "start": None, "end": None})
                    if info["can"]:
                        parts.append(f"{member.display_name} ({format_range(info['start'], info['end'])})")
                embed.add_field(
                    name=DAY_KEY_TO_DE[key],
                    value=", ".join(parts) if parts else "Keiner!",
                    inline=False,
                )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # 2) Nur Tag => Liste inkl. Zeitfenster
        if day_key and not start_t and not end_t:
            lines: List[str] = []
            for member, data in results:
                info = data.get(day_key, {"can": False, "start": None, "end": None})
                if info["can"]:
                    lines.append(f"{member.display_name} ({format_range(info['start'], info['end'])})")
            embed = discord.Embed(
                title=f"{DAY_KEY_TO_DE[day_key]}",
                description="\n".join(lines) if lines else "Keiner!",
                color=discord.Color.blurple(),
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # 3) Tag + (Start/Ende)
        if day_key and (start_t or end_t):
            want_start = hhmm_to_min(start_t) if start_t else None
            want_end   = hhmm_to_min(end_t)   if end_t   else None

            lines: List[str] = []
            for member, data in results:
                info = data.get(day_key, {"can": False, "start": None, "end": None})
                if not info["can"] or not info["start"] or not info["end"]:
                    continue
                a_start, a_end = hhmm_to_min(info["start"]), hhmm_to_min(info["end"])
                b_start = want_start if want_start is not None else 0
                b_end   = want_end   if want_end   is not None else 24 * 60 - 1
                if overlaps(a_start, a_end, b_start, b_end):
                    # NEU: wenn nur Ab -> zeige (Ende); wenn nur Bis -> zeige (Start)
                    if start_t and not end_t:
                        lines.append(f"{member.display_name} ({info['end']})")
                    elif end_t and not start_t:
                        lines.append(f"{member.display_name} ({info['start']})")
                    else:
                        # beide Zeiten angegeben -> wie gehabt: nur Namen
                        lines.append(member.display_name)

            title = f"{DAY_KEY_TO_DE[day_key]} — {format_range_with_parens(start_t, end_t)}"
            embed = discord.Embed(
                title=title,
                description="\n".join(lines) if lines else "Keiner!",
                color=discord.Color.green(),
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # 4) Nur Zeit(en) (ohne Tag) => je Nutzer die Tage; bei nur-Ab zeige (Ende), bei nur-Bis zeige (Start)
        if (start_t or end_t) and not day_key:
            want_start = hhmm_to_min(start_t) if start_t else None
            want_end   = hhmm_to_min(end_t)   if end_t   else None

            lines: List[str] = []
            for member, data in results:
                day_tokens: List[str] = []
                for key in DAY_ORDER:
                    info = data.get(key, {"can": False, "start": None, "end": None})
                    if not info["can"] or not info["start"] or not info["end"]:
                        continue
                    a_start, a_end = hhmm_to_min(info["start"]), hhmm_to_min(info["end"])
                    b_start = want_start if want_start is not None else 0
                    b_end   = want_end   if want_end   is not None else 24 * 60 - 1
                    if overlaps(a_start, a_end, b_start, b_end):
                        if start_t and not end_t:
                            day_tokens.append(f"{DAY_KEY_TO_DE[key]} ({info['end']})")
                        elif end_t and not start_t:
                            day_tokens.append(f"{DAY_KEY_TO_DE[key]} ({info['start']})")
                        else:
                            day_tokens.append(DAY_KEY_TO_DE[key])
                if day_tokens:
                    lines.append(f"{member.display_name} ({', '.join(day_tokens)})")

            title = f"Zeitfenster — {format_range_with_parens(start_t, end_t)}"
            embed = discord.Embed(
                title=title,
                description="\n".join(lines) if lines else "Keiner!",
                color=discord.Color.purple(),
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Fallback
        return await interaction.response.send_message("Ungültige Kombination.", ephemeral=True)



class ReadyTimesView(discord.ui.View):
    def __init__(self, cog: ReadyTimes, member: discord.Member, state: Dict[str, DayAvailability]):
        super().__init__(timeout=600)
        self.cog = cog
        self.member = member
        self.state = state  # key -> DayAvailability

        self.finished = False

        self.current_day_key = DAY_ORDER[0]

        # Controls
        self.day_select = DaySelect(self)
        self.add_item(self.day_select)

        self.toggle_can = ToggleCanButton(self)
        self.add_item(self.toggle_can)

        self.edit_times = EditTimesButton(self)
        self.edit_times.disabled = not self.state.get(self.current_day_key, DayAvailability()).can
        self.edit_times.label = f"Zeiten setzen ({DAY_KEY_TO_DE[self.current_day_key]})"
        self.add_item(self.edit_times)

        self.finished_btn = FinishedButton(self)
        self.add_item(self.finished_btn)

        # default set
        self.current_day_key = DAY_ORDER[0]

    async def build_embed(self) -> discord.Embed:
        emb = discord.Embed(
            title=f"Verfügbarkeiten von {self.member.display_name}",
            color=discord.Color.blurple() if not self.finished else discord.Color.green(),
        )
        status = "Bearbeitung" if not self.finished else "Fertig (read-only)"
        emb.description = (
            f"**Aktuell ausgewählt:** {DAY_KEY_TO_DE.get(self.current_day_key, '-')}\n"
            f"**Status:** {status}"
        )
        for key in DAY_ORDER:
            info = self.state.get(key, DayAvailability())
            icon = "✅" if info.can else "❌"
            text = "Kann nicht" if not info.can else format_range(info.start, info.end)
            emb.add_field(name=DAY_KEY_TO_DE[key], value=f"{icon} {text}", inline=False)

        footer = "Tag auswählen ▶️ | Ja/Nein togglen | Zeiten bearbeiten"
        if self.finished:
            footer = "Fertig – diese Ansicht ist gesperrt."
        emb.set_footer(text=footer)
        return emb


    async def refresh_message(self, interaction: discord.Interaction):
        # Wenn "Fertig": alle Controls sperren (inkl. sich selbst), sonst dynamisch je nach Tag
        if getattr(self, "finished", False):
            for item in self.children:
                item.disabled = True
        else:
            can_today = self.state.get(self.current_day_key, DayAvailability()).can
            self.edit_times.disabled = not can_today
            self.edit_times.label = f"Zeiten setzen ({DAY_KEY_TO_DE[self.current_day_key]})"

        embed = await self.build_embed()

        if getattr(self, "message_id", None):
            # Falls bereits geantwortet (z. B. nach Modal), über followup editieren
            if interaction.response.is_done():
                await interaction.followup.edit_message(self.message_id, embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)




class DaySelect(discord.ui.Select):
    def __init__(self, parent: ReadyTimesView):
        self.parent_view = parent
        options = [discord.SelectOption(label=de, value=key) for key, de in WEEKDAYS]
        super().__init__(placeholder="Wochentag wählen", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.current_day_key = self.values[0]
        await self.parent_view.refresh_message(interaction)


class ToggleCanButton(discord.ui.Button):
    def __init__(self, parent: ReadyTimesView):
        self.parent_view = parent
        super().__init__(style=discord.ButtonStyle.primary, label="Kann / Kann nicht", emoji="🔁")

    async def callback(self, interaction: discord.Interaction):
        key = self.parent_view.current_day_key
        info = self.parent_view.state.get(key, DayAvailability())
        info.can = not info.can
        if not info.can:
            # wipe times if turning off
            info.start = None
            info.end = None
        self.parent_view.state[key] = info
        # Persist
        await self.parent_view.cog.config.member(self.parent_view.member).set_raw(key, value={"can": info.can, "start": info.start, "end": info.end})
        await self.parent_view.refresh_message(interaction)


class EditTimesButton(discord.ui.Button):
    def __init__(self, parent: ReadyTimesView):
        self.parent_view = parent
        super().__init__(style=discord.ButtonStyle.secondary, label="Zeiten setzen", emoji="⏱️")
        # Disabled if current day cannot
        self.disabled = not self.parent_view.state.get(self.parent_view.current_day_key, DayAvailability()).can

    async def callback(self, interaction: discord.Interaction):
        key = self.parent_view.current_day_key
        info = self.parent_view.state.get(key, DayAvailability())
        modal = TimesModal(self.parent_view, key, info.start, info.end)
        await interaction.response.send_modal(modal)

class FinishedButton(discord.ui.Button):
    def __init__(self, parent: ReadyTimesView):
        self.parent_view = parent
        super().__init__(style=discord.ButtonStyle.success, label="Fertig!", emoji="✅")

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.finished = True
        # Optional: Label ändern, damit's sichtbar bleibt, obwohl disabled
        self.label = "Fertig ✓"
        await self.parent_view.refresh_message(interaction)



class TimesModal(discord.ui.Modal, title="Zeiten eintragen (HH:MM)"):
    start = discord.ui.TextInput(label="Von (Start)", placeholder="z. B. 19:30", required=True, max_length=5)
    end = discord.ui.TextInput(label="Bis (Ende)", placeholder="z. B. 23:00", required=True, max_length=5)

    def __init__(self, parent: ReadyTimesView, day_key: str, cur_start: Optional[str], cur_end: Optional[str]):
        super().__init__()
        self.parent_view = parent
        self.day_key = day_key
        if cur_start:
            self.start.default = cur_start
        if cur_end:
            self.end.default = cur_end

    async def on_submit(self, interaction: discord.Interaction):
        s = normalize_time_input(self.start.value)
        e = normalize_time_input(self.end.value)
        if not TIME_RE.match(s) or not TIME_RE.match(e):
            return await interaction.response.send_message("Bitte HH:MM 24h-Format verwenden.", ephemeral=True)
        if hhmm_to_min(s) >= hhmm_to_min(e):
            return await interaction.response.send_message("Ende muss nach Start liegen.", ephemeral=True)

        info = self.parent_view.state.get(self.day_key, DayAvailability(can=True))
        info.can = True
        info.start = s
        info.end = e
        self.parent_view.state[self.day_key] = info
        await self.parent_view.cog.config.member(self.parent_view.member).set_raw(self.day_key, value={"can": True, "start": s, "end": e})

        # After a modal, we must send a new response first, then edit the original ephemeral message.
        #try:
        #    await interaction.response.send_message("Gespeichert.", ephemeral=True)
        #except discord.InteractionResponded:
        #    await interaction.followup.send("Gespeichert.", ephemeral=True)

        # Find the original message to edit: interaction.message is None in modals, but the view will still be attached to the original message in memory.
        # We can safely update the embed via the View helper (using followup edit on the original message via the stored View).
        # Since we don't have the original message object here, we can refresh via a dummy edit on the parent view if interaction has a message reference.
        # Fallback: re-send the panel.
        try:
            await self.parent_view.refresh_message(interaction)
        except Exception:
            # Send a fresh panel
            emb = await self.parent_view.build_embed()
            await interaction.followup.send(embed=emb, view=self.parent_view, ephemeral=True)


async def setup(bot: Red):
    await bot.add_cog(ReadyTimes(bot))
