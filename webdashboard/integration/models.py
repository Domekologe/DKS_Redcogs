"""Declarative data models for the dashboard integration contract.

Third-party cogs return only these schemas - never raw HTML.
The frontend renders them with themeable shadcn-svelte components. This means
cog content cannot introduce an XSS attack surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# --------------------------------------------------------------------------- #
# Widgets (tiles on the central board)
# --------------------------------------------------------------------------- #
class WidgetKind(str, Enum):
    KPI = "kpi"          # single metric
    LIST = "list"        # list of entries
    CHART = "chart"      # mini chart
    STATUS = "status"    # status indicator (ok/warn/error)
    MARKDOWN = "markdown"  # safely rendered Markdown text


@dataclass
class WidgetData:
    """Data that a widget returns to the frontend."""

    kind: WidgetKind
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind.value, "payload": self.payload}

    # --- convenience constructors ---------------------------------------- #
    @classmethod
    def kpi(
        cls,
        value: Union[int, float, str],
        label: str,
        *,
        trend: Optional[str] = None,
        icon: Optional[str] = None,
        intent: str = "neutral",  # neutral | positive | negative
    ) -> "WidgetData":
        return cls(
            WidgetKind.KPI,
            {"value": value, "label": label, "trend": trend, "icon": icon, "intent": intent},
        )

    @classmethod
    def list(cls, items: List[Dict[str, Any]], *, empty: Optional[str] = None) -> "WidgetData":
        return cls(WidgetKind.LIST, {"items": items, "empty": empty})

    @classmethod
    def chart(
        cls,
        series: List[Dict[str, Any]],
        *,
        chart_type: str = "line",  # line | bar | area | doughnut
        labels: Optional[List[str]] = None,
    ) -> "WidgetData":
        return cls(WidgetKind.CHART, {"type": chart_type, "labels": labels, "series": series})

    @classmethod
    def status(cls, state: str, label: str, *, detail: Optional[str] = None) -> "WidgetData":
        return cls(WidgetKind.STATUS, {"state": state, "label": label, "detail": detail})

    @classmethod
    def markdown(cls, text: str) -> "WidgetData":
        return cls(WidgetKind.MARKDOWN, {"text": text})


# --------------------------------------------------------------------------- #
# Panels (contextual forms embedded into existing pages)
# --------------------------------------------------------------------------- #
class FieldType(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    SWITCH = "switch"
    SELECT = "select"
    MULTISELECT = "multiselect"
    CHANNEL = "channel"
    ROLE = "role"
    USER = "user"
    COLOR = "color"


@dataclass
class Field:
    key: str
    type: FieldType
    label: str
    value: Any = None
    description: Optional[str] = None
    required: bool = False
    options: Optional[List[Dict[str, Any]]] = None  # for SELECT/MULTISELECT
    min: Optional[float] = None
    max: Optional[float] = None
    max_length: Optional[int] = None
    placeholder: Optional[str] = None
    # Optional variable buttons for TEXTAREA: [{"token": "{member}", "desc": "Mitglied"}]
    variables: Optional[List[Dict[str, Any]]] = None
    # For SELECT: changing the value immediately triggers a save + reload of the panel
    # (e.g. switch profile -> fields reload).
    reload_on_change: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "key": self.key,
            "type": self.type.value,
            "label": self.label,
            "value": self.value,
            "description": self.description,
            "required": self.required,
            "options": self.options,
            "min": self.min,
            "max": self.max,
            "max_length": self.max_length,
            "placeholder": self.placeholder,
            "variables": self.variables,
            "reload_on_change": self.reload_on_change or None,
        }
        return {k: v for k, v in d.items() if v is not None}

    # --- convenience builders -------------------------------------------- #
    @classmethod
    def text(cls, key, label, *, value="", **kw):
        return cls(key, FieldType.TEXT, label, value, **kw)

    @classmethod
    def textarea(cls, key, label, *, value="", **kw):
        return cls(key, FieldType.TEXTAREA, label, value, **kw)

    @classmethod
    def number(cls, key, label, *, value=0, **kw):
        return cls(key, FieldType.NUMBER, label, value, **kw)

    @classmethod
    def switch(cls, key, label, *, value=False, **kw):
        return cls(key, FieldType.SWITCH, label, value, **kw)

    @classmethod
    def select(cls, key, label, options, *, value=None, **kw):
        return cls(key, FieldType.SELECT, label, value, options=options, **kw)

    @classmethod
    def multiselect(cls, key, label, options, *, value=None, **kw):
        return cls(key, FieldType.MULTISELECT, label, value or [], options=options, **kw)

    @classmethod
    def channel(cls, key, label, *, value=None, **kw):
        return cls(key, FieldType.CHANNEL, label, value, **kw)

    @classmethod
    def role(cls, key, label, *, value=None, **kw):
        return cls(key, FieldType.ROLE, label, value, **kw)


@dataclass
class PanelSchema:
    fields: List[Field] = field(default_factory=list)
    description: Optional[str] = None
    submit_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fields": [f.to_dict() for f in self.fields],
            "description": self.description,
            "submit_label": self.submit_label,
        }


@dataclass
class SubmitResult:
    success: bool
    message: Optional[str] = None
    errors: Optional[Dict[str, str]] = None  # field-specific errors

    def to_dict(self) -> Dict[str, Any]:
        return {"success": self.success, "message": self.message, "errors": self.errors}

    @classmethod
    def ok(cls, message: Optional[str] = None) -> "SubmitResult":
        return cls(True, message)

    @classmethod
    def fail(cls, message: str, errors: Optional[Dict[str, str]] = None) -> "SubmitResult":
        return cls(False, message, errors)


# --------------------------------------------------------------------------- #
# Pages (full standalone view - optional, component-tree schema)
# --------------------------------------------------------------------------- #
@dataclass
class Component:
    """A declarative UI building block for pages (no raw HTML)."""

    type: str  # heading | text | table | chart | panel_ref | divider | grid
    props: Dict[str, Any] = field(default_factory=dict)
    children: List["Component"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "props": self.props,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class PageSchema:
    components: List[Component] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"components": [c.to_dict() for c in self.components]}
