# ReactionRoleWeb

Ein Cog für Red-DiscordBot, das eine Weboberfläche für das ReactionRole-System über das AAA3A Dashboard bereitstellt.

## Beschreibung

ReactionRoleWeb integriert die Funktionalität des ReactionRole-Systems in das AAA3A Dashboard und ermöglicht die Verwaltung von Reaction Roles über eine benutzerfreundliche Weboberfläche.

## Voraussetzungen

- **Red-DiscordBot** Version 3.5.0 oder höher
- **AAA3A Dashboard Cog** muss installiert und geladen sein
- **Bot muss mit `--rpc` Flag gestartet werden**

## Installation

### 1. Dashboard Cog installieren

Falls noch nicht geschehen, installiere das Dashboard Cog von AAA3A:

```
[p]repo add AAA3A-cogs https://github.com/AAA3A-AAA3A/AAA3A-cogs
[p]cog install AAA3A-cogs dashboard
[p]load dashboard
```

### 2. Bot mit RPC starten

Der Bot muss mit dem `--rpc` Flag gestartet werden, damit die Dashboard-Kommunikation funktioniert:

```bash
redbot <instance_name> --rpc
```

### 3. ReactionRoleWeb Cog laden

```
[p]load reactionroleweb
```

### 4. Status überprüfen

Überprüfe, ob die Integration erfolgreich war:

```
[p]reactionroleweb-status
```

## Verwendung

### Über das Dashboard

1. Öffne das AAA3A Dashboard im Browser
2. Melde dich an und wähle deinen Server aus
3. Navigiere zu **Third Parties** → **Reaction Roles**
4. Hier kannst du:
   - Alle bestehenden Reaction Roles anzeigen
   - Neue Reaction Roles erstellen
   - Bestehende Reaction Roles entfernen
   - Reaction Roles synchronisieren

### Neue Reaction Role erstellen

1. Wähle einen Channel aus
2. Gib die Message-ID ein (Rechtsklick auf Nachricht → "ID kopieren")
3. Wähle ein Emoji aus
4. Wähle die Rolle aus, die vergeben werden soll
5. Klicke auf "Erstellen"

### Reaction Roles synchronisieren

Die Sync-Funktion fügt allen Benutzern, die bereits auf eine Nachricht reagiert haben, die entsprechende Rolle hinzu. Dies ist nützlich, wenn:
- Du eine Reaction Role nachträglich zu einer bestehenden Nachricht hinzufügst
- Rollen manuell entfernt wurden und wiederhergestellt werden sollen

## Kompatibilität

ReactionRoleWeb verwendet die gleiche Config-Struktur wie das originale ReactionRole Cog. Das bedeutet:

- ✅ Beide Cogs können parallel verwendet werden
- ✅ Im Dashboard erstellte Reaction Roles sind auch über Discord-Commands sichtbar
- ✅ Über Discord-Commands erstellte Reaction Roles sind im Dashboard sichtbar
- ✅ Daten werden zwischen beiden Cogs geteilt

## RPC-Methoden

Das Cog stellt folgende RPC-Methoden für die Dashboard-Kommunikation bereit:

| Methode | Beschreibung |
|---------|--------------|
| `rpc_get_reactionroles` | Ruft alle Reaction Roles eines Servers ab |
| `rpc_add_reactionrole` | Erstellt eine neue Reaction Role |
| `rpc_remove_reactionrole` | Entfernt eine Reaction Role |
| `rpc_sync_reactionroles` | Synchronisiert Reaction Roles mit bestehenden Reaktionen |
| `rpc_get_channels` | Ruft alle Text-Channels eines Servers ab |
| `rpc_get_roles` | Ruft alle Rollen eines Servers ab |
| `rpc_get_message` | Ruft Details zu einer Nachricht ab |

## Berechtigungen

Der Bot benötigt folgende Berechtigungen:

- **Rollen verwalten** - Zum Zuweisen/Entfernen von Rollen
- **Reaktionen hinzufügen** - Zum Hinzufügen der Emoji-Reaktionen
- **Nachrichtenverlauf lesen** - Zum Abrufen von Nachrichten

## Troubleshooting

### "Dashboard cog not found"

**Problem:** Das Dashboard Cog ist nicht installiert oder nicht geladen.

**Lösung:**
```
[p]repo add AAA3A-cogs https://github.com/AAA3A-AAA3A/AAA3A-cogs
[p]cog install AAA3A-cogs dashboard
[p]load dashboard
```

### "Integration not ready"

**Problem:** Die RPC-Integration konnte nicht hergestellt werden.

**Lösung:**
1. Stelle sicher, dass der Bot mit `--rpc` Flag gestartet wurde
2. Lade das Cog neu: `[p]reload reactionroleweb`
3. Überprüfe die Bot-Logs auf Fehler

### "No permission to read message"

**Problem:** Der Bot hat keine Berechtigung, die Nachricht zu lesen.

**Lösung:** Stelle sicher, dass der Bot im entsprechenden Channel Leserechte hat.

### "Invalid emoji"

**Problem:** Das verwendete Emoji ist ungültig oder der Bot hat keine Berechtigung, es zu verwenden.

**Lösung:**
- Verwende Standard-Discord-Emojis
- Bei Custom Emojis: Stelle sicher, dass der Bot auf dem Server ist, auf dem das Emoji existiert

## Support

Bei Problemen oder Fragen:
- Überprüfe die Bot-Logs
- Verwende `[p]reactionroleweb-status` zur Diagnose
- Erstelle ein Issue im Repository

## Version

**Version:** 1.0.0  
**Autor:** Domekologe  
**Lizenz:** Siehe LICENSE-Datei im Repository
