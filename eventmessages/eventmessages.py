import discord
from discord.ext import commands
from redbot.core import Config, app_commands, commands

EVENTS = [
    "join",
    "leave",
    "ban",
    "unban",
    "timeout",
    "timeout_end"
]

class EventMessages(commands.Cog):
    """Sendet automatisch Eventnachrichten (Join, Leave, Ban, Timeout etc.)."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=981273598123)

        default_guild = {
            "events": {
                ev: {
                    "enabled": False,
                    "channel": None
                }
                for ev in EVENTS
            }
        }

        self.config.register_guild(**default_guild)

    # ------------------------------------------------------------
    # Slash Group
    # ------------------------------------------------------------

    eventmessages = app_commands.Group(
        name="eventmessages",
        description="Einstellungen für Eventmessages"
    )

    # ------------------------------------------------------------
    # Slash: Enabled
    # ------------------------------------------------------------

    @app_commands.command(
        name="em-enabled",
        description="Event aktivieren/deaktivieren oder Status anzeigen."
    )
    @app_commands.describe(
        event="Welches Event?",
        value="true/false zum Setzen"
    )
    async def em_enabled(
        self,
        interaction: discord.Interaction,
        event: str | None = None,
        value: bool | None = None
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        if event is None:
            data = await self.config.guild(guild).events()
            msg = "**Eventstatus:**\n"
            for ev in EVENTS:
                ch = data[ev]["channel"]
                msg += f"- **{ev}**: {'Enabled' if data[ev]['enabled'] else 'Disabled'}"
                if ch:
                    msg += f" → <#{ch}>"
                msg += "\n"
            await interaction.followup.send(msg, ephemeral=True)
            return

        if event not in EVENTS:
            await interaction.followup.send(
                f"Ungültiges Event. Verwendet werden kann: `{', '.join(EVENTS)}`",
                ephemeral=True
            )
            return

        if value is None:
            await interaction.followup.send("Du musst true oder false angeben.", ephemeral=True)
            return

        await self.config.guild(guild).events[event].enabled.set(value)
        await interaction.followup.send(
            f"Event **{event}** wurde auf **{value}** gesetzt.",
            ephemeral=True
        )

    # ------------------------------------------------------------
    # Slash: Channel setzen
    # ------------------------------------------------------------

    @app_commands.command(
        name="em-channel",
        description="Setzt den Benachrichtigungschannel für ein Event."
    )
    @app_commands.describe(
        event="Welches Event?",
        channel="Channel für Benachrichtigungen"
    )
    async def em_channel(
        self,
        interaction: discord.Interaction,
        event: str,
        channel: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)

        if event not in EVENTS:
            await interaction.followup.send(
                f"Ungültiges Event. Erlaubt: `{', '.join(EVENTS)}`",
                ephemeral=True
            )
            return

        await self.config.guild(interaction.guild).events[event].channel.set(channel.id)

        await interaction.followup.send(
            f"Channel für **{event}** gesetzt auf {channel.mention}.",
            ephemeral=True
        )


    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    async def _post(self, guild: discord.Guild, event: str, message: str):
        data = await self.config.guild(guild).events()
        if not data[event]["enabled"]:
            return

        ch_id = data[event]["channel"]
        if not ch_id:
            return

        channel = guild.get_channel(ch_id)
        if channel:
            await channel.send(message)

    # ------------------------------------------------------------
    # Events
    # ------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._post(
            member.guild,
            "join",
            f"🎉 **{member.display_name}** ist dem Server beigetreten!"
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Kein Fall für Ban hier – das triggert separate Events!
        await self._post(
            member.guild,
            "leave",
            f"👋 **{member.display_name}** (`{member}`) hat den Server verlassen."
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        entry = None
        async for log in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            entry = log

        reason = entry.reason or "Kein Grund angegeben" if entry else "Unbekannt"
        moderator = entry.user.mention if entry else "Unbekannt"

        await self._post(
            guild,
            "ban",
            f"⛔ **{user.display_name}** (`{user}`) wurde gebannt.\n"
            f"👤 Moderator: {moderator}\n"
            f"📄 Grund: {reason}"
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        entry = None
        async for log in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
            entry = log

        moderator = entry.user.mention if entry else "Unbekannt"

        await self._post(
            guild,
            "unban",
            f"🔓 **{user.display_name}** (`{user}`) wurde entbannt.\n"
            f"👤 Moderator: {moderator}"
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Timeout gesetzt?
        if before.timed_out_until != after.timed_out_until:
            # Timeout END
            if before.timed_out_until and after.timed_out_until is None:
                await self._post(
                    after.guild,
                    "timeout_end",
                    f"⏱️ Timeout für **{after.display_name}** (`{after}`) ist abgelaufen."
                )
                return

            # Timeout START
            if after.timed_out_until:
                # Audit Log ziehen
                entry = None
                async for log in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                    entry = log

                moderator = entry.user.mention if entry else "Unbekannt"
                reason = entry.reason or "Kein Grund angegeben" if entry else "Unbekannt"

                duration = discord.utils.format_dt(after.timed_out_until, style="R")

                await self._post(
                    after.guild,
                    "timeout",
                    f"⛔ **{after.display_name}** (`{after}`) erhielt einen Timeout.\n"
                    f"👤 Moderator: {moderator}\n"
                    f"📄 Grund: {reason}\n"
                    f"⏳ Dauer bis: {duration}"
                )
