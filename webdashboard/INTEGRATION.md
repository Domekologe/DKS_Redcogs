# Eigene Cogs ins DKS Web Dashboard integrieren

Diese Anleitung zeigt, wie ein beliebiger Red-Cog Inhalte (Widgets, Panels, Seiten)
zum DKS Web Dashboard beiträgt – **optional** (nur wenn das Dashboard geladen ist) und
**parallel zu AAA3As Dashboard** nutzbar.

## Grundprinzipien

1. **Keine harte Abhängigkeit.** Der Cog funktioniert auch ohne `webdashboard`. Die
   Decorators werden dann zu No-ops.
2. **Opt-in zur Laufzeit.** Die Integration passiert nur, wenn der `WebDashboard`-Cog
   tatsächlich geladen ist (`bot.get_cog("WebDashboard")`).
3. **Koexistenz mit AAA3A.** Marker und Klassennamen kollidieren nicht; beide Dashboards
   dürfen gleichzeitig laufen.
4. **Nur deklarative Schemas, kein rohes HTML.** Dadurch keine XSS-Fläche.

## Schritt 1 – Drop-in-Helfer einbinden

Du hast zwei Möglichkeiten:

**A) Direkt importieren** (wenn `webdashboard` als Cog im selben Bot installiert ist):

```python
from webdashboard.integration import (
    dashboard_widget, dashboard_panel, dashboard_page,
    WidgetData, PanelSchema, PageSchema, Field, SubmitResult,
    register_dashboard, unregister_dashboard,
)
```

**B) Komplett entkoppelt** (empfohlen, wenn der Cog auch ohne `webdashboard` lauffähig
sein soll): Kopiere `webdashboard/integration/dropin.py` als `dks_dashboard.py` in deinen
Cog und importiere von dort:

```python
from .dks_dashboard import (
    dashboard_widget, dashboard_panel, WidgetData, PanelSchema, Field, SubmitResult,
    register_dashboard, unregister_dashboard, DASHBOARD_AVAILABLE,
)
```

## Schritt 2 – Beiträge dekorieren

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(welcome={"enabled": False, "message": "", "channel": None})

    # --- Widget: Kachel auf dem zentralen Board -------------------------- #
    @dashboard_widget("member_count", "Mitglieder", size="sm", refresh=60,
                      permission="guild_member")
    async def member_count(self, ctx):
        return WidgetData.kpi(value=ctx.guild.member_count, label="Mitglieder", icon="users")

    # --- Panel: kontextuelles Formular (eingebettet, keine Extra-Seite) -- #
    @dashboard_panel("welcome", "Willkommensnachricht", mount="guild_settings",
                     permission="guild_admin")
    async def welcome_panel(self, ctx):
        cfg = await self.config.guild(ctx.guild).welcome()
        return PanelSchema(fields=[
            Field.switch("enabled", "Aktiviert", value=cfg["enabled"]),
            Field.textarea("message", "Nachricht", value=cfg["message"], max_length=2000),
            Field.channel("channel", "Kanal", value=cfg["channel"]),
        ])

    @welcome_panel.on_submit
    async def save_welcome(self, ctx, data):
        await self.config.guild(ctx.guild).welcome.set(data)
        return SubmitResult.ok("Gespeichert.")
```

`ctx` ist ein `DashboardContext` mit `bot`, `user`, `guild`, `member`, `locale`. Der
Zugriff ist beim Aufruf bereits **serverseitig autorisiert** (gemäß `permission`).

### Permission-Stufen

`authenticated` · `guild_member` · `guild_mod` · `guild_admin` · `guild_owner` · `bot_owner`

## Schritt 3 – Bedingt registrieren (das „Extra")

```python
    async def cog_load(self):
        # ... deine bestehende Logik ...
        register_dashboard(self)     # integriert NUR, wenn WebDashboard geladen ist

    def cog_unload(self):
        unregister_dashboard(self)   # sicher, auch wenn nichts registriert war
        # ... deine bestehende Logik ...
```

Das war's. Ist `WebDashboard` nicht geladen, passiert schlicht nichts.

> Hinweis: Selbst wenn du `register_dashboard` weglässt, erkennt der `WebDashboard`-Cog
> beim Laden alle bereits geladenen Cogs mit dekorierten Methoden automatisch. Der
> explizite Aufruf deckt zusätzlich den Fall ab, dass dein Cog **nach** dem Dashboard
> geladen wird.

## Parallelbetrieb mit AAA3A

Du kannst beide Dashboards gleichzeitig bedienen. AAA3As Integration nutzt eine eigene
`DashboardIntegration`-Klasse und `@dashboard_page`. Um Namenskollisionen zu vermeiden,
importiere die DKS-Variante bei Bedarf unter Alias:

```python
# AAA3A
from dashboard.rpc.thirdparties import dashboard_page as aaa3a_page  # Beispiel
# DKS
from webdashboard.integration import dashboard_widget, dashboard_panel
```

- Die Marker-Attribute sind verschieden (`__dashboard_widget__`/`__dashboard_panel__`/
  `__dashboard_page__` bei DKS), daher stören sich die Scanner nicht.
- DKS registriert über `register_dashboard(self)` / den Auto-Scan und ist damit
  unabhängig von AAA3As Mixin-Vererbung. Du kannst AAA3As Mixin also normal weiter erben.
- Keines der beiden Systeme schaltet das andere ab.

## Optional: Vollständige eigene Seite

Wenn ein Cog doch eine eigene Ansicht braucht, nutze `@dashboard_page` mit einem
Komponentenbaum (`Component`) – ebenfalls ohne rohes HTML. Siehe `ARCHITECTURE.md §3.3`.
