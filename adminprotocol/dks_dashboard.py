"""Drop-in hook for the DKS web dashboard integration (no hard dependency).

This file can be copied unchanged into every cog. It also works when the
``webdashboard`` cog is not installed (the decorators then become no-ops) and can
be used alongside the AAA3A dashboard.
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
except Exception:  # webdashboard not installed
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
    """Call in ``cog_load``. Only integrates if WebDashboard is loaded."""
    dashboard = cog.bot.get_cog("WebDashboard")
    if dashboard is None:
        return False
    dashboard.register_third_party(cog)
    return True


def unregister_dashboard(cog) -> None:
    """Call in ``cog_unload`` (always safe)."""
    dashboard = cog.bot.get_cog("WebDashboard")
    if dashboard is not None:
        try:
            dashboard.unregister_third_party(cog)
        except Exception:
            pass
