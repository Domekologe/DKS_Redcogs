# -*- coding: utf-8 -*-
from redbot.core import commands, Config
import discord
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n

_ = Translator("LeaveNotifier", __file__)

@cog_i18n(_)
class LeaveNotifier(commands.Cog):
    """Sendet eine Nachricht, wenn ein Member den Server verlässt."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)

        default_guild = {
            "enabled": False,
            "channel": None,
            "message": "{user} hat den Server verlassen."
        }
        self.config.register_guild(**default_guild)

    # ============================================================
    # SLASH-KOMMANDOS
    # ============================================================

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.hybrid_group(name="leavenotifier", with_app_command=True)
    async def leavenotifier(self, ctx: commands.Context):
        """Verwaltung des Leave Notifier-Moduls."""
        pass

    @leavenotifier.command(name="enable")
    async def enable_notifier(self, ctx: commands.Context, status: bool):
        """Aktiviert oder deaktiviert das Modul."""
        await self.config.guild(ctx.guild).enabled.set(status)
        await ctx.send(_("Leave Notifier wurde {state}.").format(state="aktiviert" if status else "deaktiviert"))

    @leavenotifier.command(name="setchannel")
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Setzt den Channel, in dem die Nachricht gesendet wird."""
        await self.config.guild(ctx.guild).channel.set(channel.id)
        await ctx.send(_("Channel wurde auf {channel} gesetzt.").format(channel=channel.mention))

    @leavenotifier.command(name="setmessage")
    async def set_message(self, ctx: commands.Context, *, message: str):
        """Setzt die Nachricht. Platzhalter: {user}"""
        await self.config.guild(ctx.guild).message.set(message)
        await ctx.send(_("Nachricht wurde gesetzt auf:\n> {msg}").format(msg=message))

    @leavenotifier.command(name="showconfig")
    async def show_config(self, ctx: commands.Context):
        """Zeigt die aktuelle Konfiguration an."""
        guild_conf = await self.config.guild(ctx.guild).all()
        ch = ctx.guild.get_channel(guild_conf["channel"])
        channel_name = ch.mention if ch else "❌ Kein Channel gesetzt"
        msg = (
            f"**Aktiviert:** {guild_conf['enabled']}\n"
            f"**Channel:** {channel_name}\n"
            f"**Nachricht:** {guild_conf['message']}"
        )
        await ctx.send(msg)

    # ============================================================
    # EVENT HANDLER
    # ============================================================

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_conf = await self.config.guild(member.guild).all()
        if not guild_conf["enabled"]:
            return

        channel_id = guild_conf["channel"]
        if not channel_id:
            return

        channel = member.guild.get_channel(channel_id)
        if not channel:
            return

        msg_text = guild_conf["message"].format(user=member.display_name)
        try:
            await channel.send(msg_text)
        except discord.Forbidden:
            pass  # Keine Berechtigung

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Keine personenbezogenen Daten gespeichert."""
        return
