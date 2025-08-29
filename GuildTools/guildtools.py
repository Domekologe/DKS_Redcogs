import discord
from discord import app_commands
from redbot.core import commands, Config
from redbot.core.bot import Red
from datetime import datetime, timezone
import io
import csv

ONLINE_STATES = {discord.Status.online, discord.Status.idle, discord.Status.dnd}

class GuildTools(commands.Cog):
    """Cog: Tools für WoW-Gilden – Export der Userliste als CSV."""

    __author__ = "Domekologe"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xD0DE2025, force_registration=True)
        # Struktur: {guild_id: {member_id: iso_timestamp}}
        self.config.register_guild(last_seen={})

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

        # Logik:
        # - Wechsel in einen Online-Zustand: setze last_seen = jetzt
        # - Wechsel auf offline: setze last_seen = jetzt (Zeitpunkt des Offline-Gangs)
        became_online = after.status in ONLINE_STATES and before.status != after.status
        became_offline = after.status is discord.Status.offline and before.status != after.status

        if not (became_online or became_offline):
            return

        guild_data = await self.config.guild(after.guild).last_seen()
        member_key = str(after.id)
        guild_data[member_key] = now_iso
        await self.config.guild(after.guild).last_seen.set(guild_data)

    # ------- Slash-Command: /export-userlist -------
    @app_commands.command(name="export-userlist", description="Exportiert alle User in eine CSV (UserID|Username|Name_Auf_Server|Rolle(n)|Mitglied_Seit|Zuletzt_Online).")
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
        writer = csv.writer(buf, delimiter="|", lineterminator="\n")

        # Header exakt wie gewünscht
        writer.writerow(["UserID", "Username", "Name_Auf_Server", "Rolle(n)", "Mitglied_Seit", "Zuletzt_Online"])

        # Zeilen
        for m in members:
            user_id = str(m.id)
            username = m.name  # globaler Username
            name_auf_server = m.display_name  # Nickname/Servername
            rollen = ", ".join([r.name for r in m.roles if r.name != "@everyone"]) or ""
            # Mitglied_Seit
            if m.joined_at:
                joined = m.joined_at.astimezone(timezone.utc).isoformat()
            else:
                joined = ""
            # Zuletzt_Online aus Tracking oder unbekannt
            zuletzt_online = last_seen_map.get(user_id, "unbekannt")

            writer.writerow([user_id, username, name_auf_server, rollen, joined, zuletzt_online])

        # Datei vorbereiten
        buf.seek(0)
        filename = f"user_export_{guild.id}.csv"
        file = discord.File(fp=io.BytesIO(buf.getvalue().encode("utf-8-sig")), filename=filename)

        await interaction.followup.send(
            content="Hier ist dein Export (nur für dich sichtbar).",
            file=file,
            ephemeral=True,
        )

async def setup(bot: Red):
    await bot.add_cog(GuildTools(bot))
