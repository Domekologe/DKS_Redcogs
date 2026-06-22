"""Drop-in-Hook für Dritt-Cogs (Referenz-Implementierung).

Kopiere diese Datei als ``dks_dashboard.py`` in deinen Cog ODER importiere sie direkt
(``from webdashboard.integration.dropin import ...``), wenn WebDashboard ohnehin als
Cog im selben Bot installiert ist.

Eigenschaften:
* **Keine harte Abhängigkeit** – funktioniert auch, wenn ``webdashboard`` nicht
  installiert ist (Decorators werden dann zu No-ops).
* **Opt-in zur Laufzeit** – ``register_dashboard`` integriert nur, wenn der
  ``WebDashboard``-Cog tatsächlich geladen ist; sonst passiert nichts.
* **AAA3A-kompatibel** – kollidiert nicht mit AAA3As ``DashboardIntegration`` /
  ``@dashboard_page``; beide Dashboards können gleichzeitig laufen. Importiere bei
  Bedarf unter Alias (siehe INTEGRATION.md).
"""
from __future__ import annotations

try:
    # Aus den Submodulen importieren, damit dies sowohl als interner Import
    # (innerhalb des webdashboard-Pakets) als auch als kopierte Datei in einem
    # fremden Cog funktioniert.
    try:
        from .context import DashboardContext  # type: ignore  # noqa: F401
        from .decorators import (  # type: ignore  # noqa: F401
            dashboard_page,
            dashboard_panel,
            dashboard_widget,
        )
        from .models import (  # type: ignore  # noqa: F401
            Component,
            Field,
            PageSchema,
            PanelSchema,
            SubmitResult,
            WidgetData,
        )
    except ImportError:
        # als kopierte Datei (kein Paketkontext): absoluter Import
        from webdashboard.integration.context import DashboardContext  # type: ignore  # noqa: F401,E501
        from webdashboard.integration.decorators import (  # type: ignore  # noqa: F401
            dashboard_page,
            dashboard_panel,
            dashboard_widget,
        )
        from webdashboard.integration.models import (  # type: ignore  # noqa: F401
            Component,
            Field,
            PageSchema,
            PanelSchema,
            SubmitResult,
            WidgetData,
        )

    DASHBOARD_AVAILABLE = True
except Exception:  # pragma: no cover - webdashboard nicht installiert
    DASHBOARD_AVAILABLE = False

    def _noop_decorator(*_args, **_kwargs):
        def deco(func):
            return func

        return deco

    # Decorators werden zu No-ops; markierte Methoden bleiben normale Methoden.
    def _noop_panel(*_args, **_kwargs):
        def deco(func):
            def on_submit(sub):
                return sub

            func.on_submit = on_submit
            return func

        return deco

    dashboard_widget = dashboard_page = _noop_decorator  # type: ignore
    dashboard_panel = _noop_panel  # type: ignore

    class _Stub:
        """Platzhalter, falls die Datenklassen ohne geladenes Dashboard genutzt werden."""

        def __init__(self, *_a, **_k):
            ...

        def to_dict(self):
            return {}

        @classmethod
        def _factory(cls, *_a, **_k):
            return cls()

        # gängige Konstruktoren
        kpi = list = chart = status = markdown = ok = fail = _factory  # type: ignore

    WidgetData = PanelSchema = PageSchema = Field = Component = SubmitResult = _Stub  # type: ignore
    DashboardContext = object  # type: ignore


def register_dashboard(cog) -> bool:
    """In ``cog_load`` aufrufen. Integriert NUR, wenn WebDashboard geladen ist.

    Liefert ``True``, wenn registriert wurde, sonst ``False``.
    """
    dashboard = cog.bot.get_cog("WebDashboard")
    if dashboard is None:
        return False
    dashboard.register_third_party(cog)
    return True


def unregister_dashboard(cog) -> None:
    """In ``cog_unload`` aufrufen (sicher, auch wenn nichts registriert war)."""
    dashboard = cog.bot.get_cog("WebDashboard")
    if dashboard is not None:
        try:
            dashboard.unregister_third_party(cog)
        except Exception:
            pass
