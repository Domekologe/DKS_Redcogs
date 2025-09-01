import discord
from discord import app_commands
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from datetime import datetime, timezone
import io
import csv
import asyncio
import re
import os

ONLINE_STATES = {discord.Status.online, discord.Status.idle, discord.Status.dnd}
DATE_FORMATS = ["%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"]

def _parse_date(s: str) -> datetime | None:
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def _out_date(dt: datetime) -> str:
    # Einheitliches Ausgabeformat in Datei/CSV
    return dt.strftime("%d.%m.%Y")

class GuildTools(commands.Cog):
    """Cog: Tools für WoW-Gilden – Export & Abwesenheiten."""

    __author__ = "Domekologe"
    __version__ = "1.1.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xD0DE2025, force_registration=True)
        # Struktur: {guild_id: {member_id: iso_timestamp}}
        self.config.register_guild(last_seen={})
        # File-Lock für Abwesenheits-Datei-IO
        self._abs_lock = asyncio.Lock()

    # ------- Presence-Tracking für "Zuletzt_Online" -------
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        # Nur in Guilds arbeiten; DM-User ignorieren
        if not after.guild:
            return

        # Wenn wir keine Presence-Daten bekommen, hilft alles nix
        intents = getattr(self.bot, "intents", None)
        if not intents or not intents.presences:
            return

        now_iso = datetime.now(timezone.utc).isoformat()

        # Wechsel-Logik
        became_online = after.status in ONLINE_STATES and before.status != after.status
        became_offline = after.status is discord.Status.offline and before.status != after.status

        if not (became_online or became_offline):
            return

        guild_data = await self.config.guild(after.guild).last_seen()
        member_key = str(after.id)
        guild_data[member_key] = now_iso
        await self.config.guild(after.guild).last_seen.set(guild_data)

    # ------- Slash-Command: /export-userlist -------
    @app_commands.command(name="export-userlist", description="Exportiert alle User in eine CSV.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def export_userlist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("Dieser Befehl muss in einer Guild ausgeführt werden.", ephemeral=True)

        # Members zuverlässig holen (auch ungecachte)
        members = []
        try:
            async for m in guild.fetch_members(limit=None):
                members.append(m)
        except discord.Forbidden:
            return await interaction.followup.send(
                "Mir fehlen Berechtigungen, um Mitglieder zu lesen. Bitte gib mir **Mitglieder anzeigen** (View Guild Members).",
                ephemeral=True
            )

        # Presence-Cache laden
        last_seen_map = await self.config.guild(guild).last_seen()

        # CSV in Memory bauen
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";", lineterminator="\n")  # Spaltentrenner ';'

        # Header
        writer.writerow(["UserID", "Username", "Name_Auf_Server", "Rolle(n)", "Mitglied_Seit", "Zuletzt_Online"])

        # Zeilen
        for m in members:
            user_id = str(m.id)
            username = m.name
            name_auf_server = m.display_name
            rollen = ", ".join([r.name for r in m.roles if r.name != "@everyone"]) or ""
            joined = m.joined_at.astimezone(timezone.utc).isoformat() if m.joined_at else ""
            zuletzt_online = last_seen_map.get(user_id, "unbekannt")

            writer.writerow([user_id, username, name_auf_server, rollen, joined, zuletzt_online])

        # Datei schreiben (BOM für Excel)
        buf.seek(0)
        filename = f"user_export_{guild.id}.csv"
        file = discord.File(fp=io.BytesIO(buf.getvalue().encode("utf-8-sig")), filename=filename)

        await interaction.followup.send(
            content="Hier ist dein Export (nur für dich sichtbar).",
            file=file,
            ephemeral=True,
        )

    # ------- Slash-Command: /add-absence -------
    @app_commands.command(
        name="add-absence",
        description="Trage eine Abwesenheit ein (Format: Tag-Monat-Jahr; z. B. 01-09-2025 / 01.09.2025 / 01/09/2025)."
    )
    @app_commands.describe(
        von="Startdatum deiner Abwesenheit (z. B. 01-09-2025 oder 01.09.2025)",
        bis="Enddatum deiner Abwesenheit (z. B. 05-09-2025 oder 05.09.2025)",
    )
    @app_commands.guild_only()
    async def add_absence(self, interaction: discord.Interaction, von: str, bis: str):
        start = _parse_date(von)
        end = _parse_date(bis)

        if not start:
            return await interaction.response.send_message(
                "❌ Ungültiges **von**-Datum. Erlaubt sind `DD-MM-YYYY`, `DD.MM.YYYY`, `DD/MM/YYYY`.",
                ephemeral=True,
            )
        if not end:
            return await interaction.response.send_message(
                "❌ Ungültiges **bis**-Datum. Erlaubt sind `DD-MM-YEEE`, `DD.MM.YYYY`, `DD/MM/YYYY`.",
                ephemeral=True,
            )
        if end < start:
            return await interaction.response.send_message(
                "❌ **bis** darf nicht vor **von** liegen.",
                ephemeral=True,
            )
        if (end - start).days > 365:
            return await interaction.response.send_message(
                "❌ Abwesenheiten dürfen max. 365 Tage umfassen.",
                ephemeral=True,
            )

        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Dieser Befehl muss in einer Guild ausgeführt werden.", ephemeral=True)

        # Datei: absences_<guildid>.txt im Cog-Datenordner
        data_dir = cog_data_path(raw_name=self.__class__.__name__)
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / f"absences_{guild.id}.txt"

        # Zeile vorbereiten
        row = [
            str(interaction.user.id),
            interaction.user.name,
            interaction.user.display_name,
            _out_date(start),
            _out_date(end),
        ]
        line = ";".join(row) + "\n"

        # Thread-sicher schreiben
        async with self._abs_lock:
            # Datei anlegen, falls nicht vorhanden, mit Header
            new_file = not path.exists()
            # Schreiben in Thread (Datei-IO blockiert)
            def _write():
                with open(path, "a", encoding="utf-8") as f:
                    if new_file:
                        f.write("UserID;Username;Name auf Server;Von;Bis\n")
                    f.write(line)
            await asyncio.to_thread(_write)

        # Ephemeral Bestätigung
        await interaction.response.send_message(
            f"✅ Abwesenheit gespeichert für **{interaction.user.mention}**\n"
            f"• Von: **{_out_date(start)}**\n"
            f"• Bis: **{_out_date(end)}**\n"
            f"(Eintrag liegt in der Gilden-Abwesenheitsdatei.)",
            ephemeral=True,
        )

    # ------- Slash-Command: /get-absence (nur Mods) -------
    @app_commands.command(
        name="get-absence",
        description="Erstellt eine CSV mit allen Abwesenheiten (Delimiter ';')."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def get_absence(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("Dieser Befehl muss in einer Guild ausgeführt werden.", ephemeral=True)

        data_dir = cog_data_path(raw_name=self.__class__.__name__)
        path = data_dir / f"absences_{guild.id}.txt"

        if not path.exists():
            return await interaction.followup.send("Keine Abwesenheiten gefunden.", ephemeral=True)

        # Datei lesen & als CSV (mit BOM) zurückgeben
        async with self._abs_lock:
            def _read_all() -> str:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            content = await asyncio.to_thread(_read_all)

        # Wir liefern als CSV-Datei aus (gleiches Format/Delimiter, aber mit UTF-8-BOM für Excel)
        out_bytes = ("\ufeff" + content).encode("utf-8")  # BOM hinzufügen
        filename = f"absences_{guild.id}.csv"
        file = discord.File(io.BytesIO(out_bytes), filename=filename)

        await interaction.followup.send(
            content="Hier ist die Abwesenheitsliste (nur für dich sichtbar).",
            file=file,
            ephemeral=True,
        )

async def setup(bot: Red):
    await bot.add_cog(GuildTools(bot))
