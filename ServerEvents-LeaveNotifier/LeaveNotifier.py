import discord
from redbot.core import commands, Config, app_commands
from datetime import datetime

class ServerEventsLeaveNotifier(commands.Cog):
    """Notifies when a user leaves the server."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(leave_channel=None)

    # Nur mit Mod-Rechten nutzbar
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.command(name="event-set-leave-channel", description="Set the channel for leave notifications")
    async def set_leave_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.config.guild(interaction.guild).leave_channel.set(channel.id)
        await interaction.response.send_message(f"Leave-Channel wurde auf {channel.mention} gesetzt.", ephemeral=True)

    # Eventlistener für Austritte
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel_id = await self.config.guild(member.guild).leave_channel()
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            return

        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        msg = f"Benutzer {member.display_name} ({member.name}#{member.discriminator}) hat den Server am {timestamp} verlassen!"
        await channel.send(msg)

async def setup(bot):
    await bot.add_cog(ServerEventsLeaveNotifier(bot))
