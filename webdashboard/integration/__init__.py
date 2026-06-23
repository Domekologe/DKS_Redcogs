"""Public integration API of the DKS Web Dashboard.

Third-party cogs import from here::

    from webdashboard.integration import (
        DashboardIntegration, dashboard_widget, dashboard_panel, dashboard_page,
        DashboardContext, WidgetData, PanelSchema, PageSchema,
        Field, Component, SubmitResult,
        register_dashboard, unregister_dashboard, DASHBOARD_AVAILABLE,
    )
"""
from .base import DashboardIntegration
from .context import DashboardContext
from .decorators import (
    dashboard_list,
    dashboard_page,
    dashboard_panel,
    dashboard_widget,
    iter_contributions,
)
from .models import (
    Component,
    Field,
    FieldType,
    PageSchema,
    PanelSchema,
    SubmitResult,
    WidgetData,
    WidgetKind,
)
from .registry import Contribution, Registry
from .dropin import (
    DASHBOARD_AVAILABLE,
    register_dashboard,
    unregister_dashboard,
)

__all__ = [
    "DashboardIntegration",
    "DashboardContext",
    "dashboard_widget",
    "dashboard_panel",
    "dashboard_page",
    "dashboard_list",
    "iter_contributions",
    "WidgetData",
    "WidgetKind",
    "PanelSchema",
    "PageSchema",
    "Field",
    "FieldType",
    "Component",
    "SubmitResult",
    "Registry",
    "Contribution",
    "register_dashboard",
    "unregister_dashboard",
    "DASHBOARD_AVAILABLE",
]
