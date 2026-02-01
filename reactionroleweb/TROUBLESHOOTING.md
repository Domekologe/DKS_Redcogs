# ReactionRoleWeb Troubleshooting

## Problem: Cog erscheint nicht im Third-party Bereich des Webinterfaces

### Schritt 1: Überprüfen Sie die Voraussetzungen

1. **Dashboard Cog installiert?**
   ```
   [p]cog list
   ```
   Suchen Sie nach "Dashboard" in der Liste.

2. **Bot mit --rpc Flag gestartet?**
   Der Bot MUSS mit dem `--rpc` Flag gestartet werden, damit das Dashboard funktioniert:
   ```
   python -m redbot <botname> --rpc
   ```

3. **Dashboard Cog geladen?**
   ```
   [p]load dashboard
   ```

### Schritt 2: Status überprüfen

Verwenden Sie den Status-Befehl:
```
[p]reactionroleweb-status
```

Dieser Befehl zeigt an:
- Ob das Dashboard Cog gefunden wurde
- Ob die Integration erfolgreich war
- Wo Sie das Interface finden können

### Schritt 3: Logs überprüfen

Überprüfen Sie die Bot-Logs auf Fehlermeldungen:
- Suchen Sie nach `red.dks_redcogs.reactionroleweb`
- Achten Sie auf ERROR oder WARNING Meldungen

### Schritt 4: Cog neu laden

Manchmal hilft es, das Cog neu zu laden:
```
[p]reload reactionroleweb
```

### Schritt 5: Dashboard API Version überprüfen

Das AAA3A Dashboard Cog könnte eine andere API-Version verwenden. Um dies zu debuggen:

1. Öffnen Sie die Python-Konsole des Bots:
   ```
   [p]debug
   ```

2. Führen Sie folgenden Code aus:
   ```python
   dashboard = bot.get_cog("Dashboard")
   if dashboard:
       print(f"Dashboard gefunden: {dashboard}")
       if hasattr(dashboard, 'rpc'):
           print(f"RPC vorhanden: {dashboard.rpc}")
           if hasattr(dashboard.rpc, 'third_parties_handler'):
               handler = dashboard.rpc.third_parties_handler
               print(f"Handler gefunden: {handler}")
               print(f"Handler Attribute: {dir(handler)}")
           else:
               print("Kein third_parties_handler gefunden")
       else:
           print("Kein RPC gefunden - Bot mit --rpc starten!")
   else:
       print("Dashboard Cog nicht geladen")
   ```

### Häufige Probleme

1. **Bot nicht mit --rpc gestartet**
   - Lösung: Bot mit `--rpc` Flag neu starten

2. **Dashboard Cog nicht installiert**
   - Lösung: 
     ```
     [p]repo add AAA3A-cogs https://github.com/AAA3A-AAA3A/AAA3A-cogs
     [p]cog install AAA3A-cogs dashboard
     [p]load dashboard
     ```

3. **Inkompatible Dashboard Version**
   - Lösung: Dashboard Cog aktualisieren:
     ```
     [p]cog update dashboard
     ```

4. **Registrierung schlägt fehl**
   - Überprüfen Sie die Logs
   - Versuchen Sie, beide Cogs neu zu laden:
     ```
     [p]reload dashboard
     [p]reload reactionroleweb
     ```

### Alternative: Manuelle Registrierung

Falls die automatische Registrierung nicht funktioniert, können Sie versuchen, das Cog manuell zu registrieren. Öffnen Sie die Debug-Konsole und führen Sie aus:

```python
dashboard = bot.get_cog("Dashboard")
reactionroleweb = bot.get_cog("ReactionRoleWeb")

if dashboard and reactionroleweb and hasattr(dashboard, 'rpc'):
    handler = dashboard.rpc.third_parties_handler
    # Versuchen Sie verschiedene Registrierungsmethoden
    handler.third_parties["reactionrole"] = {
        "name": "Reaction Roles",
        "description": "Manage reaction roles",
        "cog": reactionroleweb
    }
    print("Manuelle Registrierung erfolgreich")
```

### Kontakt

Wenn das Problem weiterhin besteht, erstellen Sie ein Issue mit:
- Bot-Version (`[p]info`)
- Dashboard Cog Version
- Relevante Log-Ausgaben
- Ausgabe des Debug-Befehls aus Schritt 5
