"""Drop-in-Hook für die DKS-Web-Dashboard-Integration (keine harte Abhängigkeit).

Diese Datei kann unverändert in jeden Cog kopiert werden. Sie funktioniert auch, wenn
der ``webdashboard``-Cog nicht installiert ist (Decorators werden dann zu No-ops) und ist
parallel zum AAA3A-Dashboard nutzbar.
"""
from __future__ import annotations

try:
    from webdashboard.integration.context import DashboardContext  # noqa: F401
    from webdashboard.integration.decorators import (  # noqa: F401
        dashboard_page,
        dashboard_panel,
        dashboard_widget,
    )
    from webdashboard.integration.models import (  # noqa: F401
        Component,
        Field,
        PageSchema,
        PanelSchema,
        SubmitResult,
        WidgetData,
    )

    DASHBOARD_AVAILABLE = True
except Exception:  # webdashboard nicht installiert
    DASHBOARD_AVAILABLE = False

    def _noop_decorator(*_args, **_kwargs):
        def deco(func):
            return func

        return deco

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
        def __init__(self, *_a, **_k):
            ...

        def to_dict(self):
            return {}

        @classmethod
        def _factory(cls, *_a, **_k):
            return cls()

        kpi = list = chart = status = markdown = ok = fail = _factory  # type: ignore

    WidgetData = PanelSchema = PageSchema = Field = Component = SubmitResult = _Stub  # type: ignore
    DashboardContext = object  # type: ignore


def register_dashboard(cog) -> bool:
    """In ``cog_load`` aufrufen. Integriert nur, wenn WebDashboard geladen ist."""
    dashboard = cog.bot.get_cog("WebDashboard")
    if dashboard is None:
        return False
    dashboard.register_third_party(cog)
    return True


def unregister_dashboard(cog) -> None:
    """In ``cog_unload`` aufrufen (immer sicher)."""
    dashboard = cog.bot.get_cog("WebDashboard")
    if dashboard is not None:
        try:
            dashboard.unregister_third_party(cog)
        except Exception:
            pass
