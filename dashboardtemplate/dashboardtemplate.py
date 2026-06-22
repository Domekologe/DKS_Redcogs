"""
DashboardTemplate — Referenz-/Vorlage-Cog für die DKS-Web-Dashboard-Integration.

Dieses Cog macht nichts Sinnvolles; es ist eine kommentierte Vorlage, an der du
zeigst/abschaust, wie man einen bestehenden Cog ans Web-Dashboard anbindet
(„migriert"). Es demonstriert:

  1) Den Drop-in-Import (keine harte Abhängigkeit, AAA3A-koexistent).
  2) Bedingte Registrierung in cog_load / cog_unload.
  3) Ein Widget (Kachel auf dem Board).
  4) Ein Guild-Panel mit allen praktisch nutzbaren Feldtypen + Speichern.
  5) Ein globales Panel (nur Bot-Owner), z. B. für API-Keys.

Migrations-Kurzfassung (von AAA3As @dashboard_page):
  - AAA3A: eine Methode liefert rohes HTML/Jinja je Cog -> eigene Seite.
  - DKS:   du lieferst deklarative Schemas (PanelSchema/Field) -> wird in ein
           gemeinsames, themebares UI gerendert. Pro Einstellung ein Field,
           gespeichert über @<panel>.on_submit. Kein HTML, keine XSS-Fläche.
Beide können gleichzeitig im selben Cog existieren (siehe README.md).
"""
from __future__ import annotations

from typing import Any

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

# ---- 1) Drop-in-Import -------------------------------------------------------
# `dks_dashboard.py` liegt im selben Cog-Ordner. Bei nicht installiertem
# webdashboard sind das No-ops -> der Cog lädt trotzdem ganz normal.
from .dks_dashboard import (
    dashboard_widget,
    dashboard_panel,
    dashboard_list,
    WidgetData,
    PanelSchema,
    Field,
    SubmitResult,
    register_dashboard,
    unregister_dashboard,
)


class DashboardTemplate(commands.Cog):
    """Vorlage: zeigt Widget + Guild-Panel + globales Panel."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x7E5701E1, force_registration=True)

        # Pro-Guild-Einstellungen (werden im Guild-Panel bearbeitet).
        self.config.register_guild(
            language="de-DE",   # pro-Guild Sprache dieses Cogs (de-DE | en-US)
            enabled=False,
            greeting="Willkommen, {member}!",
            max_warns=3,
            mode="soft",
            log_channel=None,   # speichert eine Channel-ID (oder None)
            staff_role=None,    # speichert eine Rollen-ID (oder None)
            items={},           # Beispiel-Sammlung: {id: {"name", "note"}} – für die Liste
        )
        # Globale Einstellungen (werden im globalen Panel bearbeitet, Owner-only).
        self.config.register_global(
            api_key="",
            region="eu",
        )

    # ---- 2) Lifecycle: bedingt registrieren ---------------------------------
    async def cog_load(self) -> None:
        # WICHTIG: register_dashboard als erste relevante Zeile. Tut nichts,
        # wenn das Dashboard nicht geladen ist; integriert sonst diesen Cog.
        register_dashboard(self)
        # ... hier ggf. deine eigene Lade-Logik ...

    def cog_unload(self) -> None:
        unregister_dashboard(self)
        # ... hier ggf. dein eigenes Aufräumen ...

    # ---- 3) Widget: Kachel auf dem zentralen Board --------------------------
    # Erscheint auf der Server-Detailseite unter „Übersicht".
    # size: sm | md | lg ; refresh: Auto-Refresh in Sekunden (optional).
    # permission: authenticated | guild_member | guild_mod | guild_admin |
    #             guild_owner | bot_owner
    @dashboard_widget("status", "Vorlage-Status", size="sm", refresh=60, permission="guild_member")
    async def status_widget(self, ctx):
        try:
            enabled = await self.config.guild(ctx.guild).enabled()
            # Statt KPI gehen auch: WidgetData.list(...), .status(...), .chart(...), .markdown(...)
            return WidgetData.status(
                state="ok" if enabled else "warn",
                label="Aktiv" if enabled else "Inaktiv",
                detail="Beispiel-Widget",
            )
        except Exception:
            return WidgetData.status(state="error", label="Fehler")

    # ---- 4) Guild-Panel: alle nützlichen Feldtypen --------------------------
    # mount="guild_settings" -> erscheint auf der Server-Detailseite unter
    # „Einstellungen" (aufklappbar). permission="guild_admin" empfohlen.
    # order=10 -> Reihenfolge der Tabs im Modul (kleiner = weiter links).
    @dashboard_panel("settings", "Vorlage-Einstellungen", mount="guild_settings", permission="guild_admin", order=10)
    async def settings_panel(self, ctx):
        cfg = await self.config.guild(ctx.guild).all()

        # Channel-/Rollen-Auswahl: das Frontend hat (noch) keinen eigenen
        # Channel-/Rollen-Picker -> als SELECT mit Optionen liefern.
        channel_options = [{"value": "", "label": "— kein Kanal —"}] + [
            {"value": str(c.id), "label": "#" + c.name} for c in ctx.guild.text_channels
        ]
        role_options = [{"value": "", "label": "— keine Rolle —"}] + [
            {"value": str(r.id), "label": r.name}
            for r in ctx.guild.roles
            if not r.is_default()
        ]

        return PanelSchema(
            description="Beispiel-Panel mit allen praktisch nutzbaren Feldtypen.",
            submit_label="Speichern",
            fields=[
                # Sprache dieses Moduls (pro Guild) – DE/EN-Umschaltung.
                # reload_on_change=True: beim Ändern wird sofort gespeichert UND das Panel
                # neu geladen (praktisch, wenn andere Felder von der Auswahl abhängen).
                Field.select(
                    "language", "Sprache (dieses Modul)",
                    [{"value": "de-DE", "label": "Deutsch"}, {"value": "en-US", "label": "English"}],
                    value=cfg["language"],
                    reload_on_change=True,
                ),
                # Schalter (bool)
                Field.switch("enabled", "Modul aktiviert", value=bool(cfg["enabled"])),
                # Mehrzeiliger Text mit Variablen-Buttons (fügen Tokens an Cursor ein)
                Field.textarea(
                    "greeting", "Begrüßung", value=cfg["greeting"], max_length=500,
                    variables=[
                        {"token": "{member}", "desc": "Mitglied"},
                        {"token": "{server}", "desc": "Server"},
                    ],
                ),
                # Zahl mit Grenzen
                Field.number("max_warns", "Max. Verwarnungen", value=cfg["max_warns"], min=0, max=10),
                # Auswahl (fixe Optionen)
                Field.select(
                    "mode", "Modus",
                    [{"value": "soft", "label": "Soft"}, {"value": "hard", "label": "Hart"}],
                    value=cfg["mode"],
                ),
                # Kanal-Auswahl (als Select mit Channel-Optionen)
                Field.select("log_channel", "Log-Kanal", channel_options, value=str(cfg["log_channel"] or "")),
                # Rollen-Auswahl (als Select mit Rollen-Optionen)
                Field.select("staff_role", "Staff-Rolle", role_options, value=str(cfg["staff_role"] or "")),
                # Einfaches Textfeld
                # Field.text("note", "Notiz", value=""),
            ],
        )

    # Speicher-Handler. `data` ist ein flaches Dict {field_key: wert}.
    @settings_panel.on_submit
    async def save_settings(self, ctx, data):
        g = self.config.guild(ctx.guild)
        if "language" in data:
            await g.language.set("en-US" if data["language"] == "en-US" else "de-DE")
        if "enabled" in data:
            await g.enabled.set(bool(data["enabled"]))
        if "greeting" in data:
            await g.greeting.set(str(data["greeting"])[:500])
        if "max_warns" in data:
            try:
                await g.max_warns.set(max(0, min(10, int(data["max_warns"]))))
            except (TypeError, ValueError):
                return SubmitResult.fail("Max. Verwarnungen muss eine Zahl sein.",
                                         errors={"max_warns": "Ungültige Zahl"})
        if "mode" in data:
            await g.mode.set("hard" if data["mode"] == "hard" else "soft")
        # Channel-/Rollen-IDs: leeres Feld -> None, sonst int.
        if "log_channel" in data:
            v = data["log_channel"]
            await g.log_channel.set(int(v) if v else None)
        if "staff_role" in data:
            v = data["staff_role"]
            await g.staff_role.set(int(v) if v else None)
        return SubmitResult.ok("Einstellungen gespeichert.")

    # ---- 5) Globales Panel: nur Bot-Owner (z. B. API-Keys) ------------------
    # scope="global" + mount="bot_settings" -> erscheint auf /settings unter
    # „Modul-Einstellungen (global)". permission="bot_owner".
    @dashboard_panel("api", "Vorlage API & Global", scope="global", mount="bot_settings", permission="bot_owner")
    async def global_panel(self, ctx):
        # ctx.guild ist hier None (globaler Kontext) -> NICHT auf ctx.guild zugreifen.
        return PanelSchema(
            description="Globale Einstellungen dieses Moduls (Owner-only).",
            fields=[
                Field.text("api_key", "API-Schlüssel", value=await self.config.api_key()),
                Field.select(
                    "region", "Region",
                    [{"value": "eu", "label": "EU"}, {"value": "us", "label": "US"}],
                    value=await self.config.region(),
                ),
            ],
        )

    @global_panel.on_submit
    async def save_global(self, ctx, data):
        if "api_key" in data:
            await self.config.api_key.set(str(data["api_key"]).strip())
        if "region" in data:
            await self.config.region.set("us" if data["region"] == "us" else "eu")
        return SubmitResult.ok("Global gespeichert.")

    # ---- 6) Liste: anlegen / ansehen / bearbeiten / löschen -----------------
    # @dashboard_list rendert eine Tabelle mit Aktionen. Die Methode liefert Zeilen
    # [{"id": ..., "cells": {spalten_key: wert}}]. Optional: @<list>.on_delete /
    # @<list>.edit_form (liefert ein PanelSchema) / @<list>.on_edit (speichert).
    @dashboard_list(
        "items", "Vorlage-Liste", mount="guild_settings", permission="guild_admin", order=30,
        columns=[{"key": "name", "label": "Name"}, {"key": "note", "label": "Notiz"}],
        description="Beispiel-Liste: anlegen (Tab links), bearbeiten und löschen.",
    )
    async def items_list(self, ctx):
        items = await self.config.guild(ctx.guild).items()
        return [
            {"id": str(k), "cells": {"name": str(v.get("name", k)), "note": str(v.get("note", ""))}}
            for k, v in (items or {}).items() if isinstance(v, dict)
        ]

    @items_list.edit_form
    async def items_edit_form(self, ctx, item_id):
        items = await self.config.guild(ctx.guild).items()
        entry = (items or {}).get(str(item_id)) or {}
        return PanelSchema(fields=[
            Field.text("name", "Name", value=str(entry.get("name", ""))),
            Field.text("note", "Notiz", value=str(entry.get("note", ""))),
        ])

    @items_list.on_edit
    async def items_edit(self, ctx, item_id, data):
        async with self.config.guild(ctx.guild).items() as items:
            entry = items.get(str(item_id)) if isinstance(items.get(str(item_id)), dict) else {}
            entry["name"] = str(data.get("name", "")).strip() or entry.get("name", "")
            entry["note"] = str(data.get("note", ""))
            items[str(item_id)] = entry
        return SubmitResult.ok("Eintrag aktualisiert.")

    @items_list.on_delete
    async def items_delete(self, ctx, item_id):
        async with self.config.guild(ctx.guild).items() as items:
            if str(item_id) in items:
                del items[str(item_id)]
            else:
                return SubmitResult.fail("Eintrag nicht gefunden.")
        return SubmitResult.ok("Eintrag gelöscht.")

    # Anlegen-Panel (order=25 -> Tab links neben der Liste bei order=30).
    @dashboard_panel("item_add", "Eintrag anlegen", mount="guild_settings", permission="guild_admin", order=25)
    async def item_add_panel(self, ctx):
        return PanelSchema(
            description="Neuen Listen-Eintrag anlegen.",
            submit_label="Anlegen",
            fields=[
                Field.text("name", "Name", value="", placeholder="z. B. Regel 1"),
                Field.text("note", "Notiz", value=""),
            ],
        )

    @item_add_panel.on_submit
    async def item_add(self, ctx, data):
        import uuid
        name = str(data.get("name", "")).strip()
        if not name:
            return SubmitResult.fail("Bitte einen Namen angeben.")
        async with self.config.guild(ctx.guild).items() as items:
            items[uuid.uuid4().hex[:8]] = {"name": name, "note": str(data.get("note", ""))}
        return SubmitResult.ok("Eintrag angelegt.")

    # ---- Owner-Command zum schnellen Prüfen ---------------------------------
    @commands.is_owner()
    @commands.command(name="dashboardtemplate")
    async def _status(self, ctx: commands.Context) -> None:
        loaded = self.bot.get_cog("WebDashboard") is not None
        await ctx.send(f"WebDashboard geladen: {loaded}. Panels: settings (guild), api (global).")
