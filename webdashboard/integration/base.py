"""``DashboardIntegration`` – Mixin, von dem Dritt-Cogs erben.

Verwendung in einem Cog::

    from redbot.core import commands
    # Pfad ggf. an die eigene Installation anpassen:
    from webdashboard.integration import (
        DashboardIntegration, dashboard_widget, dashboard_panel,
        WidgetData, PanelSchema, Field, SubmitResult,
    )

    class MyCog(DashboardIntegration, commands.Cog):
        def __init__(self, bot):
            self.bot = bot

        @dashboard_widget("hello", "Hallo")
        async def hello_widget(self, ctx):
            return WidgetData.kpi(value=42, label="Antwort")

Der Mixin meldet den Cog beim ``WebDashboard``-Cog an, sobald dieser verfügbar ist –
auch wenn das Dashboard erst nach dem Dritt-Cog geladen wird.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("red.dks.webdashboard.integration")


class DashboardIntegration:
    """Mixin für Dritt-Cogs, die sich ins DKS Web Dashboard integrieren."""

    bot: Any  # von der Cog-Klasse bereitgestellt

    async def cog_load(self) -> None:  # type: ignore[override]
        # eigene cog_load-Logik der Unterklasse zuerst ausführen
        parent_load = getattr(super(), "cog_load", None)
        if parent_load is not None:
            await parent_load()
        self._register_with_dashboard()

    def cog_unload(self) -> None:  # type: ignore[override]
        dashboard = self.bot.get_cog("WebDashboard")
        if dashboard is not None:
            try:
                dashboard.unregister_third_party(self)
            except Exception:
                log.exception("Fehler beim Abmelden vom WebDashboard")
        parent_unload = getattr(super(), "cog_unload", None)
        if parent_unload is not None:
            parent_unload()

    def _register_with_dashboard(self) -> None:
        dashboard = self.bot.get_cog("WebDashboard")
        if dashboard is None:
            # Dashboard noch nicht geladen – es holt uns nach, sobald es lädt.
            log.debug("WebDashboard noch nicht geladen; Registrierung wird nachgeholt.")
            return
        try:
            dashboard.register_third_party(self)
        except Exception:
            log.exception("Fehler beim Registrieren am WebDashboard")
