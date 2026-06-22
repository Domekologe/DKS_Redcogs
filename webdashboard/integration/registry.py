"""Zentrale Sammelstelle für alle Dashboard-Beiträge der registrierten Cogs."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .decorators import iter_contributions

log = logging.getLogger("red.dks.webdashboard.registry")


@dataclass
class Contribution:
    cog_name: str
    cog: Any
    kind: str            # widget | panel | page
    identifier: str
    meta: Any            # _ContributionMeta
    handler: Callable    # gebundene Methode (liefert Daten/Schema/Zeilen)
    submit: Optional[Callable] = None  # nur Panels
    delete: Optional[Callable] = None  # nur Listen
    edit: Optional[Callable] = None        # nur Listen (Speichern)
    edit_form: Optional[Callable] = None   # nur Listen (Formular)

    @property
    def key(self) -> str:
        return f"{self.cog_name}:{self.identifier}"

    def manifest(self) -> Dict[str, Any]:
        m = self.meta.manifest()
        m["cog"] = self.cog_name
        m["key"] = self.key
        if self.kind == "list":
            m["deletable"] = self.delete is not None
            m["editable"] = self.edit is not None and self.edit_form is not None
        return m


@dataclass
class Registry:
    _contribs: Dict[str, Contribution] = field(default_factory=dict)

    # --- Registrierung ---------------------------------------------------- #
    def register_cog(self, cog: Any) -> int:
        """Scannt einen Cog nach dekorierten Methoden und nimmt sie auf."""
        cog_name = type(cog).__name__
        count = 0
        for _attr, meta, bound in iter_contributions(cog):
            submit = None
            if meta.kind == "panel" and meta.submit_handler is not None:
                # gebundenen Submit-Handler am Cog auflösen
                submit = getattr(cog, meta.submit_handler.__name__, None)
            delete = edit = edit_form = None
            if meta.kind == "list":
                if meta.delete_handler is not None:
                    delete = getattr(cog, meta.delete_handler.__name__, None)
                if meta.edit_handler is not None:
                    edit = getattr(cog, meta.edit_handler.__name__, None)
                if meta.edit_form_handler is not None:
                    edit_form = getattr(cog, meta.edit_form_handler.__name__, None)
            contrib = Contribution(
                cog_name=cog_name,
                cog=cog,
                kind=meta.kind,
                identifier=meta.identifier,
                meta=meta,
                handler=bound,
                submit=submit,
                delete=delete,
                edit=edit,
                edit_form=edit_form,
            )
            self._contribs[contrib.key] = contrib
            count += 1
        log.info("Registriert: %d Beiträge von Cog %s", count, cog_name)
        return count

    def unregister_cog(self, cog: Any) -> None:
        cog_name = type(cog).__name__
        for key in [k for k, c in self._contribs.items() if c.cog_name == cog_name]:
            del self._contribs[key]
        log.info("Beiträge von Cog %s entfernt", cog_name)

    # --- Abfrage ---------------------------------------------------------- #
    def get(self, key: str) -> Optional[Contribution]:
        return self._contribs.get(key)

    def all(self) -> List[Contribution]:
        return list(self._contribs.values())

    def by_kind(self, kind: str) -> List[Contribution]:
        return [c for c in self._contribs.values() if c.kind == kind]

    def manifest(self) -> List[Dict[str, Any]]:
        return [c.manifest() for c in self._contribs.values()]
