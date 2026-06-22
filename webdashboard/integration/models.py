"""Deklarative Datenmodelle für den Dashboard-Integrations-Contract.

Dritt-Cogs liefern ausschließlich diese Schemas zurück – niemals rohes HTML.
Das Frontend rendert sie mit themebaren shadcn-svelte-Komponenten. Dadurch gibt es
keine XSS-Angriffsfläche durch Cog-Inhalte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# --------------------------------------------------------------------------- #
# Widgets (Kacheln auf dem zentralen Board)
# --------------------------------------------------------------------------- #
class WidgetKind(str, Enum):
    KPI = "kpi"          # einzelne Kennzahl
    LIST = "list"        # Liste aus Einträgen
    CHART = "chart"      # Mini-Diagramm
    STATUS = "status"    # Statusanzeige (ok/warn/error)
    MARKDOWN = "markdown"  # sicher gerenderter Markdown-Text


@dataclass
class WidgetData:
    """Daten, die ein Widget an das Frontend liefert."""

    kind: WidgetKind
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind.value, "payload": self.payload}

    # --- bequeme Konstruktoren ------------------------------------------- #
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
# Panels (kontextuelle Formulare, eingebettet in bestehende Seiten)
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
    options: Optional[List[Dict[str, Any]]] = None  # für SELECT/MULTISELECT
    min: Optional[float] = None
    max: Optional[float] = None
    max_length: Optional[int] = None
    placeholder: Optional[str] = None

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
        }
        return {k: v for k, v in d.items() if v is not None}

    # --- Convenience-Builder --------------------------------------------- #
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
    errors: Optional[Dict[str, str]] = None  # feldspezifische Fehler

    def to_dict(self) -> Dict[str, Any]:
        return {"success": self.success, "message": self.message, "errors": self.errors}

    @classmethod
    def ok(cls, message: Optional[str] = None) -> "SubmitResult":
        return cls(True, message)

    @classmethod
    def fail(cls, message: str, errors: Optional[Dict[str, str]] = None) -> "SubmitResult":
        return cls(False, message, errors)


# --------------------------------------------------------------------------- #
# Pages (vollwertige eigene Ansicht – optional, Komponentenbaum-Schema)
# --------------------------------------------------------------------------- #
@dataclass
class Component:
    """Ein deklarativer UI-Baustein für Pages (kein rohes HTML)."""

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
