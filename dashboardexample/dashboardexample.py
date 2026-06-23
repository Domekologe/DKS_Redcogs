"""Example cog: shows integration into the DKS web dashboard.

Demonstrates a widget (KPI), a panel (form with saving) and conditional
registration. Also works without WebDashboard installed.
"""
from __future__ import annotations

from redbot.core import Config, commands
from redbot.core.bot import Red

from .dks_dashboard import (
    DASHBOARD_AVAILABLE,
    Field,
    PanelSchema,
    SubmitResult,
    WidgetData,
    dashboard_panel,
    dashboard_widget,
    register_dashboard,
    unregister_dashboard,
)


class DashboardExample(commands.Cog):
    """Small example cog for the web dashboard integration."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xDA5B0A4D, force_registration=True)
        self.config.register_guild(
            greeting={"enabled": False, "message": "Willkommen!", "channel": None}
        )

    # ------------------------------------------------------------------ #
    # Lifecycle – the "extra": only integrate when the dashboard is present
    # ------------------------------------------------------------------ #
    async def cog_load(self) -> None:
        register_dashboard(self)  # No-op if WebDashboard is not loaded

    def cog_unload(self) -> None:
        unregister_dashboard(self)

    # ------------------------------------------------------------------ #
    # Widget – appears as a tile on the central board
    # ------------------------------------------------------------------ #
    @dashboard_widget(
        "member_count", "Mitglieder", size="sm", refresh=60, permission="guild_member"
    )
    async def member_count_widget(self, ctx):
        guild = ctx.guild
        if guild is None:
            return WidgetData.kpi(value="–", label="Mitglieder")
        return WidgetData.kpi(value=guild.member_count, label="Mitglieder", icon="users")

    # ------------------------------------------------------------------ #
    # Panel – contextual form (embedded, not its own page)
    # ------------------------------------------------------------------ #
    @dashboard_panel(
        "greeting", "Begrüßung", mount="guild_settings", permission="guild_admin"
    )
    async def greeting_panel(self, ctx):
        cfg = await self.config.guild(ctx.guild).greeting()
        return PanelSchema(
            description="Begrüßungsnachricht für neue Mitglieder.",
            fields=[
                Field.switch("enabled", "Aktiviert", value=cfg["enabled"]),
                Field.textarea("message", "Nachricht", value=cfg["message"], max_length=1000),
                Field.channel("channel", "Kanal", value=cfg["channel"]),
            ],
        )

    @greeting_panel.on_submit
    async def save_greeting(self, ctx, data):
        await self.config.guild(ctx.guild).greeting.set(
            {
                "enabled": bool(data.get("enabled")),
                "message": str(data.get("message", ""))[:1000],
                "channel": data.get("channel"),
            }
        )
        return SubmitResult.ok("Begrüßung gespeichert.")

    # ------------------------------------------------------------------ #
    # Owner command for a quick check
    # ------------------------------------------------------------------ #
    @commands.is_owner()
    @commands.command(name="dashboardexample")
    async def _status(self, ctx: commands.Context) -> None:
        state = "verfügbar" if DASHBOARD_AVAILABLE else "nicht installiert"
        loaded = self.bot.get_cog("WebDashboard") is not None
        await ctx.send(
            f"WebDashboard-Integration: {state}; Cog geladen: {loaded}."
        )
