# WebDashboard (Companion-Cog)

Eigenes, modulares und sicheres Web-Dashboard-System für Red-DiscordBot. Dieser Cog ist
die **Bot-Seite**: er stellt ein RPC-Gateway bereit und sammelt die Beiträge anderer Cogs
(Widgets, Panels, Seiten). Das **Frontend** ist die separate SvelteKit-App
`DKS_Redbot_WebApp`.

- Architektur: [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- Eigene Cogs anbinden: [`INTEGRATION.md`](./INTEGRATION.md)

## Installation (Cog)

```
[p]repo add dks-redcogs <REPO_URL>
[p]cog install dks-redcogs webdashboard
[p]load webdashboard
```

## Einrichtung & Verbindung mit der Web-App

Das Zusammenspiel besteht aus drei Geheimnissen/Adressen, die zueinander passen müssen.

### 1. Gateway im Bot starten

Beim Laden startet das Gateway automatisch auf `127.0.0.1:6970` (nur localhost).
Prüfen:

```
[p]dashboard status
```

Adresse/Port ändern (z. B. wenn 6970 belegt ist):

```
[p]dashboard bind 127.0.0.1 6970
[p]dashboard stop
[p]dashboard start
```

> **Sicherheit:** Lass das Gateway auf `127.0.0.1`. Mache es nach außen nur über einen
> Reverse-Proxy (TLS) oder einen Tunnel erreichbar – nicht direkt an `0.0.0.0` binden.

### 2. Gateway-Token abrufen

```
[p]dashboard token
```

Der Bot schickt dir das Token per DM. Dieses Token kennt **nur** der SvelteKit-Server
(BFF) – niemals der Browser. Neues Token erzeugen (invalidiert das alte):

```
[p]dashboard regen
```

### 3. Web-App konfigurieren

In `DKS_Redbot_WebApp/.env`:

```dotenv
GATEWAY_URL=http://127.0.0.1:6970     # gleiche Adresse wie [p]dashboard bind
GATEWAY_TOKEN=<das per DM erhaltene Token>
DISCORD_CLIENT_ID=...                  # Discord Developer Portal
DISCORD_CLIENT_SECRET=...
DISCORD_REDIRECT_URI=http://localhost:5173/auth/callback
SESSION_SECRET=<openssl rand -hex 32>
```

Im [Discord Developer Portal](https://discord.com/developers/applications) unter
**OAuth2 → Redirects** exakt dieselbe `DISCORD_REDIRECT_URI` eintragen.

### 4. Web-App starten

```
cd DKS_Redbot_WebApp
npm install
npm run dev        # http://localhost:5173
```

Login per Discord → das Board zeigt automatisch alle Widgets/Panels der Cogs, für die
du berechtigt bist.

## Owner-Commands

| Command | Funktion |
|---|---|
| `[p]dashboard status` | Status, Adresse, Anzahl registrierter Beiträge |
| `[p]dashboard start` / `stop` | Gateway starten/stoppen |
| `[p]dashboard bind <host> <port>` | Adresse setzen (Neustart nötig) |
| `[p]dashboard token` | Token per DM |
| `[p]dashboard regen` | Neues Token erzeugen + Neustart |

## Wie Cogs sich anbinden

Andere Cogs dekorieren Methoden mit `@dashboard_widget` / `@dashboard_panel` und rufen in
`cog_load` `register_dashboard(self)` auf. Das geschieht **optional** – ohne geladenes
WebDashboard passiert nichts – und ist **parallel zu AAA3A** nutzbar. Vollständige
Anleitung: [`INTEGRATION.md`](./INTEGRATION.md). Ein lauffähiges Beispiel liegt im Cog
`dashboardexample` in diesem Repo.

## Konnektivität & Troubleshooting

- **Web-App erreicht das Gateway nicht?** Prüfe `[p]dashboard status` (läuft es?), ob
  `GATEWAY_URL`/Port übereinstimmen und ob `GATEWAY_TOKEN` korrekt ist.
- **Web-App in Docker, Bot auf dem Host:** Das Gateway lauscht standardmäßig nur auf
  `127.0.0.1` – das ist aus einem Container **nicht** erreichbar. Dann entweder den Bot
  ebenfalls containerisieren und ins selbe Docker-Netz hängen, oder das Gateway bewusst auf
  eine erreichbare Adresse binden (`[p]dashboard bind 0.0.0.0 6970`) **und** den Port per
  Firewall absichern. In der Web-App dann `GATEWAY_URL=http://host.docker.internal:6970`.
- **Keine Server / keine Widgets sichtbar, obwohl berechtigt?** Reds Member-Cache: Ohne den
  privilegierten **Server Members Intent** (im Discord Developer Portal aktivieren) kennt
  der Bot die Mitglieder nicht, und die Rechteauflösung pro Server (Admin/Mod/Member) liefert
  dann nur `authenticated`. Intent aktivieren und Bot neu starten.
- **Health-Check:** `GET http://127.0.0.1:6970/api/health` liefert ohne Token `{"status":"ok"}`.
  Alle anderen Endpunkte verlangen das Token.

## Sicherheit (Kurzfassung)

- Gateway nur auf localhost, Token-Auth (konstant-Zeit-Vergleich) zwischen BFF und Cog.
- Discord-OAuth2 im BFF; Berechtigungen werden **serverseitig** aus Reds Rechtesystem
  abgeleitet und bei jedem Aufruf erzwungen.
- Cogs liefern nur deklarative Schemas (kein rohes HTML) → keine XSS-Fläche.
- Schreibende Aktionen werden auditiert (Log).
