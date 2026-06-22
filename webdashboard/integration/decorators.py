"""Decorators, mit denen Dritt-Cogs Beiträge zum Dashboard markieren.

Beispiele siehe ARCHITECTURE.md §3. Die Decorators hängen nur Metadaten an die
Methode an; das Einsammeln übernimmt die Registry beim Registrieren des Cogs.
"""
from __future__ import annotations

import functools
from typing import Any, Callable, List, Optional

WIDGET_ATTR = "__dashboard_widget__"
PANEL_ATTR = "__dashboard_panel__"
PAGE_ATTR = "__dashboard_page__"


class _ContributionMeta:
    """Gemeinsame Metadaten-Basis für alle Beitragstypen."""

    def __init__(
        self,
        kind: str,
        identifier: str,
        name: str,
        *,
        permission: str = "authenticated",
        description: Optional[str] = None,
        icon: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        self.kind = kind
        self.identifier = identifier
        self.name = name
        self.permission = permission
        self.description = description
        self.icon = icon
        self.extra = extra or {}
        # wird bei Panels gesetzt
        self.submit_handler: Optional[Callable] = None

    def manifest(self) -> dict:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "name": self.name,
            "permission": self.permission,
            "description": self.description,
            "icon": self.icon,
            **self.extra,
        }


def dashboard_widget(
    identifier: str,
    name: str,
    *,
    size: str = "md",            # sm | md | lg
    refresh: Optional[int] = None,  # Auto-Refresh in Sekunden
    permission: str = "authenticated",
    scope: str = "guild",        # guild | global
    description: Optional[str] = None,
    icon: Optional[str] = None,
) -> Callable:
    """Registriert eine Methode als Board-Widget."""

    def decorator(func: Callable) -> Callable:
        meta = _ContributionMeta(
            "widget", identifier, name,
            permission=permission, description=description, icon=icon,
            extra={"size": size, "refresh": refresh, "scope": scope},
        )
        setattr(func, WIDGET_ATTR, meta)
        return func

    return decorator


def dashboard_panel(
    identifier: str,
    name: str,
    *,
    mount: str = "guild_settings",  # Einbettungsort im UI
    permission: str = "guild_admin",
    scope: str = "guild",
    description: Optional[str] = None,
    icon: Optional[str] = None,
) -> Callable:
    """Registriert eine Methode als kontextuelles Panel (Formular).

    Der zugehörige Speicher-Handler wird über ``@<panel>.on_submit`` gesetzt.
    """

    def decorator(func: Callable) -> Callable:
        meta = _ContributionMeta(
            "panel", identifier, name,
            permission=permission, description=description, icon=icon,
            extra={"mount": mount, "scope": scope},
        )
        setattr(func, PANEL_ATTR, meta)

        def on_submit(submit_func: Callable) -> Callable:
            meta.submit_handler = submit_func
            setattr(submit_func, PANEL_ATTR + "_submit", identifier)
            return submit_func

        func.on_submit = on_submit  # type: ignore[attr-defined]
        return func

    return decorator


def dashboard_page(
    identifier: str,
    name: str,
    *,
    permission: str = "authenticated",
    scope: str = "guild",
    description: Optional[str] = None,
    icon: Optional[str] = None,
    nav: bool = True,  # in der Seitennavigation anzeigen?
) -> Callable:
    """Registriert eine Methode als vollwertige Seite (Komponentenbaum-Schema)."""

    def decorator(func: Callable) -> Callable:
        meta = _ContributionMeta(
            "page", identifier, name,
            permission=permission, description=description, icon=icon,
            extra={"scope": scope, "nav": nav},
        )
        setattr(func, PAGE_ATTR, meta)
        return func

    return decorator


def iter_contributions(cog: Any) -> List[tuple]:
    """Liefert ``(attr, meta, bound_method)`` für alle dekorierten Methoden eines Cogs."""
    found = []
    for attr_name in dir(cog):
        try:
            member = getattr(cog, attr_name)
        except Exception:
            continue
        if not callable(member):
            continue
        func = getattr(member, "__func__", member)
        for marker in (WIDGET_ATTR, PANEL_ATTR, PAGE_ATTR):
            meta = getattr(func, marker, None)
            if meta is not None:
                found.append((attr_name, meta, member))
                break
    return found
