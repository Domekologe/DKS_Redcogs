"""DKS Web Dashboard – Companion-Cog.

Stellt das RPC-Gateway bereit und verwaltet die Integrations-Registry, in die sich
andere Cogs mit Widgets, Panels und Seiten eintragen.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any, Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import box

from .gateway import Gateway
from .integration.base import DashboardIntegration
from .integration.registry import Registry

log = logging.getLogger("red.dks.webdashboard")
_ = Translator("WebDashboard", __file__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6970


@cog_i18n(_)
class WebDashboard(commands.Cog):
    """Eigenes, modulares Web-Dashboard-System für Red.

    Cogs binden sich integriert ein (Widgets + kontextuelle Panels), statt eine
    eigene Extra-Seite zu erzeugen.
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xD8B0A12D, force_registration=True)
        self.config.register_global(
            token=None,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            autostart=True,
        )
        self.registry = Registry()
        self.gateway: Optional[Gateway] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def cog_load(self) -> None:
        # Bereits geladene Dritt-Cogs einsammeln – unabhängig davon, ob sie das
        # DashboardIntegration-Mixin nutzen oder nur Methoden dekoriert + sich später
        # registriert hätten. So funktioniert jede Lade-Reihenfolge.
        from .integration.decorators import iter_contributions
        for cog in self.bot.cogs.values():
            if isinstance(cog, DashboardIntegration) or iter_contributions(cog):
                self.registry.register_cog(cog)
        if await self.config.autostart():
            await self._start_gateway()

    async def cog_unload(self) -> None:
        await self._stop_gateway()

    async def _start_gateway(self) -> None:
        if self.gateway is not None:
            return
        token = await self.config.token()
        if not token:
            token = secrets.token_urlsafe(48)
            await self.config.token.set(token)
        host = await self.config.host()
        port = await self.config.port()
        self.gateway = Gateway(self.bot, self.registry, token=token, host=host, port=port)
        try:
            await self.gateway.start()
        except Exception:
            log.exception("Gateway konnte nicht gestartet werden")
            self.gateway = None
            raise

    async def _stop_gateway(self) -> None:
        if self.gateway is not None:
            await self.gateway.stop()
            self.gateway = None

    # ------------------------------------------------------------------ #
    # Öffentliche Integrations-API (von DashboardIntegration genutzt)
    # ------------------------------------------------------------------ #
    def register_third_party(self, cog: Any) -> int:
        """Registriert die Dashboard-Beiträge eines Dritt-Cogs."""
        return self.registry.register_cog(cog)

    def unregister_third_party(self, cog: Any) -> None:
        self.registry.unregister_cog(cog)

    # ------------------------------------------------------------------ #
    # Commands (nur Bot-Owner)
    # ------------------------------------------------------------------ #
    @commands.is_owner()
    @commands.group(name="dksdashboard", aliases=["dksdash"])
    async def dashboard_group(self, ctx: commands.Context) -> None:
        """Verwaltung des DKS Web-Dashboards.

        Hinweis: Eigener Befehlsname, damit es parallel zu AAA3As `[p]dashboard`
        laufen kann.
        """

    @dashboard_group.command(name="status")
    async def dashboard_status(self, ctx: commands.Context) -> None:
        """Zeigt den aktuellen Status des Gateways."""
        running = self.gateway is not None
        host = await self.config.host()
        port = await self.config.port()
        contribs = len(self.registry.all())
        cogs = len({c.cog_name for c in self.registry.all()})
        lines = [
            _("Status: {state}").format(state=_("läuft") if running else _("gestoppt")),
            _("Adresse: http://{host}:{port}").format(host=host, port=port),
            _("Registrierte Beiträge: {n} (aus {c} Cogs)").format(n=contribs, c=cogs),
        ]
        await ctx.send(box("\n".join(lines)))

    @dashboard_group.command(name="start")
    async def dashboard_start(self, ctx: commands.Context) -> None:
        """Startet das Gateway."""
        try:
            await self._start_gateway()
        except Exception as e:
            await ctx.send(_("Start fehlgeschlagen: {error}").format(error=e))
            return
        await ctx.send(_("Gateway gestartet."))

    @dashboard_group.command(name="stop")
    async def dashboard_stop(self, ctx: commands.Context) -> None:
        """Stoppt das Gateway."""
        await self._stop_gateway()
        await ctx.send(_("Gateway gestoppt."))

    @dashboard_group.command(name="bind")
    async def dashboard_bind(self, ctx: commands.Context, host: str, port: int) -> None:
        """Setzt Host und Port (Neustart nötig).

        Hinweis: Aus Sicherheitsgründen sollte das Gateway nur auf 127.0.0.1 lauschen
        und extern über einen Reverse-Proxy/Tunnel erreichbar gemacht werden.
        """
        await self.config.host.set(host)
        await self.config.port.set(port)
        await ctx.send(_("Gespeichert: {host}:{port}. Bitte neu starten.").format(host=host, port=port))

    @dashboard_group.command(name="token")
    async def dashboard_token(self, ctx: commands.Context) -> None:
        """Sendet das Gateway-Token per DM (für die Web-App-Konfiguration)."""
        token = await self.config.token()
        if not token:
            token = secrets.token_urlsafe(48)
            await self.config.token.set(token)
        try:
            await ctx.author.send(box(token))
            await ctx.send(_("Token per DM gesendet."))
        except discord.Forbidden:
            await ctx.send(_("Ich konnte dir keine DM senden. Bitte DMs aktivieren."))

    @dashboard_group.command(name="regen")
    async def dashboard_regen(self, ctx: commands.Context) -> None:
        """Erzeugt ein neues Gateway-Token (Web-App muss aktualisiert werden)."""
        token = secrets.token_urlsafe(48)
        await self.config.token.set(token)
        await self._stop_gateway()
        await self._start_gateway()
        await ctx.send(_("Neues Token erzeugt und Gateway neu gestartet. Hole es mit `[p]dksdashboard token`."))
