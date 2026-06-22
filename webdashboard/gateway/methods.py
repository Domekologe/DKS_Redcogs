"""Core-RPC-Methoden des Gateways.

Konvention für ``params``::

    {
      "auth": {"user_id": "123", "guild_id": "456", "locale": "de-DE"},
      "args": { ... methodenspezifisch ... }
    }

Die Auth-Angaben stammen vom (vertrauenswürdigen) BFF, der den Discord-OAuth2-Login
bereits durchgeführt hat. Berechtigungen werden hier serverseitig erneut geprüft.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from ..integration.context import DashboardContext
from ..permissions import _level_value, has_permission, resolve_level
from .rpc import (
    FORBIDDEN,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    UNAUTHORIZED,
    Dispatcher,
    RpcError,
)

log = logging.getLogger("red.dks.webdashboard.methods")

dispatcher = Dispatcher()


class _LightUser:
    """Minimaler User-Stellvertreter (nur ID), falls der echte User weder im Cache
    liegt noch per API abrufbar ist. Reicht für alle Permission-Checks (id-basiert)
    und vermeidet ein hartes Fehlschlagen bei Cache-/Netzwerkproblemen."""

    __slots__ = ("id", "name", "bot")

    def __init__(self, uid: int) -> None:
        self.id = uid
        self.name = None
        self.bot = False


# --------------------------------------------------------------------------- #
# Hilfen
# --------------------------------------------------------------------------- #
async def _build_context(gateway: Any, params: Dict[str, Any]) -> DashboardContext:
    bot = gateway.bot
    auth = params.get("auth") or {}
    user_id = auth.get("user_id")
    if not user_id:
        raise RpcError(UNAUTHORIZED, "Kein authentifizierter Benutzer im Request")

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        raise RpcError(INVALID_PARAMS, "Ungültige user_id")

    user = bot.get_user(uid)
    if user is None:
        try:
            user = await bot.fetch_user(uid)
        except Exception:
            # Kein harter Fehler: id-basierte Permission-Checks funktionieren weiter.
            user = _LightUser(uid)

    guild = None
    member = None
    gid = auth.get("guild_id")
    if gid:
        guild = bot.get_guild(int(gid))
        if guild is not None:
            member = guild.get_member(uid)

    return DashboardContext(
        bot=bot,
        user=user,
        guild=guild,
        member=member,
        locale=auth.get("locale", "en-US"),
        params=params.get("args") or {},
    )


async def _require(gateway: Any, ctx: DashboardContext, permission: str) -> None:
    # Lock: ist das Dashboard gesperrt, dürfen nur Bot-Owner geschützte Calls ausführen.
    cog = gateway.bot.get_cog("WebDashboard")
    if cog is not None:
        try:
            if await cog.config.locked() and not await gateway.bot.is_owner(ctx.user):
                raise RpcError(FORBIDDEN, "Dashboard ist gesperrt")
        except RpcError:
            raise
        except Exception:
            pass
    if not await has_permission(gateway.bot, ctx.user, permission, ctx.guild):
        raise RpcError(FORBIDDEN, f"Berechtigung '{permission}' erforderlich")


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
@dispatcher.method("core.botinfo")
async def core_botinfo(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    bot = gateway.bot
    user = bot.user
    latency_ms = round(bot.latency * 1000) if bot.latency else None
    return {
        "name": user.name if user else None,
        "id": str(user.id) if user else None,
        "avatar": str(user.display_avatar.url) if user else None,
        "guild_count": len(bot.guilds),
        "latency_ms": latency_ms,
        "is_owner": await bot.is_owner(ctx.user),
    }


@dispatcher.method("core.guilds")
async def core_guilds(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Guilds, in denen der User Rechte hat (mit höchster Stufe je Guild)."""
    ctx = await _build_context(gateway, params)
    bot = gateway.bot
    is_owner = await bot.is_owner(ctx.user)  # einmal berechnen
    result = []
    for guild in bot.guilds:
        if guild.get_member(ctx.user.id) is None and not is_owner:
            continue
        level = await resolve_level(bot, ctx.user, guild)
        if level < 1:  # weniger als guild_member
            continue
        result.append({
            "id": str(guild.id),
            "name": guild.name,
            "icon": str(guild.icon.url) if guild.icon else None,
            "member_count": guild.member_count,
            "level": int(level),
        })
    return {"guilds": result}


@dispatcher.method("core.guild_detail")
async def core_guild_detail(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Detailübersicht einer Guild (Mitglieder, Kanäle, Rollen, Status, Daten)."""
    ctx = await _build_context(gateway, params)
    if ctx.guild is None:
        raise RpcError(INVALID_PARAMS, "Unbekannte Guild")
    await _require(gateway, ctx, "guild_member")
    g = ctx.guild

    online = idle = dnd = offline = 0
    try:
        for m in g.members:
            s = str(getattr(m, "status", "offline"))
            if s == "online":
                online += 1
            elif s == "idle":
                idle += 1
            elif s == "dnd":
                dnd += 1
            else:
                offline += 1
    except Exception:
        pass

    owner = g.owner
    me = g.me
    return {
        "id": str(g.id),
        "name": g.name,
        "icon": str(g.icon.url) if g.icon else None,
        "owner": (owner.display_name if owner else None),
        "member_count": g.member_count,
        "channels": {
            "text": len(g.text_channels),
            "voice": len(g.voice_channels),
            "categories": len(g.categories),
            "total": len(g.text_channels) + len(g.voice_channels),
        },
        "roles": len(g.roles),
        "presence": {"online": online, "idle": idle, "dnd": dnd, "offline": offline},
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "joined_at": me.joined_at.isoformat() if me and me.joined_at else None,
    }


# --------------------------------------------------------------------------- #
# Öffentliche Befehlsübersicht (KEIN Login nötig – nur aktive Commands)
# --------------------------------------------------------------------------- #
@dispatcher.method("core.commands")
async def core_commands(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Liste der aktiven Text- und Slash-Commands. Öffentlich (ohne User-Kontext).

    Es werden nur sichtbare, aktivierte Commands ausgegeben (keine versteckten).
    """
    bot = gateway.bot

    prefix: list = []
    try:
        for c in bot.walk_commands():
            if getattr(c, "hidden", False) or not getattr(c, "enabled", True):
                continue
            prefix.append({
                "name": c.qualified_name,
                "description": (getattr(c, "short_doc", "") or "").strip(),
                "cog": c.cog_name or "—",
            })
    except Exception:
        log.exception("Fehler beim Sammeln der Text-Commands")

    slash: list = []
    try:
        from discord import app_commands  # lokal, um harte Importabhängigkeit zu meiden

        tree = getattr(bot, "tree", None)
        if tree is not None:
            for c in tree.walk_commands():
                if not isinstance(c, app_commands.Command):
                    continue  # Gruppen ohne eigenen Callback überspringen
                binding = getattr(c, "binding", None)
                slash.append({
                    "name": c.qualified_name,
                    "description": (getattr(c, "description", "") or "").strip(),
                    "cog": type(binding).__name__ if binding is not None else "—",
                })
    except Exception:
        log.exception("Fehler beim Sammeln der Slash-Commands")

    # eindeutige, sortierte Ausgabe
    seen_p, uniq_p = set(), []
    for c in sorted(prefix, key=lambda x: x["name"]):
        if c["name"] in seen_p:
            continue
        seen_p.add(c["name"]); uniq_p.append(c)
    seen_s, uniq_s = set(), []
    for c in sorted(slash, key=lambda x: x["name"]):
        if c["name"] in seen_s:
            continue
        seen_s.add(c["name"]); uniq_s.append(c)

    return {
        "bot": {"name": bot.user.name if bot.user else None,
                "avatar": str(bot.user.display_avatar.url) if bot.user else None},
        "prefix": uniq_p,
        "slash": uniq_s,
        "counts": {"prefix": len(uniq_p), "slash": len(uniq_s)},
    }


@dispatcher.method("core.stats")
async def core_stats(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Öffentliche Bot-Statistik für die Landing/Übersicht (ohne Login)."""
    bot = gateway.bot
    cog = _dashboard_cog(gateway)
    ui = (await cog.config.ui()) if cog else {}

    owner = None
    try:
        oid = next(iter(getattr(bot, "owner_ids", []) or []), None)
        if oid:
            u = bot.get_user(oid)
            owner = u.name if u else None
    except Exception:
        owner = None

    uptime_s = None
    up = getattr(bot, "uptime", None)
    if up is not None:
        try:
            now = datetime.now(up.tzinfo) if getattr(up, "tzinfo", None) else datetime.utcnow()
            uptime_s = int((now - up).total_seconds())
        except Exception:
            uptime_s = None

    return {
        "name": bot.user.name if bot.user else None,
        "avatar": str(bot.user.display_avatar.url) if bot.user else None,
        "owner": owner,
        "description": ui.get("description") or "",
        "guild_count": len(bot.guilds),
        "user_count": len(bot.users),
        "uptime_s": uptime_s,
        "latency_ms": round(bot.latency * 1000) if bot.latency else None,
    }


# --------------------------------------------------------------------------- #
# Manifest & Beiträge (Widgets / Panels / Pages)
# --------------------------------------------------------------------------- #
@dispatcher.method("manifest.get")
async def manifest_get(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Liefert alle Beiträge, die der User sehen darf (gefiltert nach Rechten)."""
    ctx = await _build_context(gateway, params)
    # Permission-Stufe nur EINMAL auflösen und dann vergleichen (statt teurer
    # Auflösung pro Beitrag – spart bei vielen Cogs zahlreiche Config-Reads).
    level = await resolve_level(gateway.bot, ctx.user, ctx.guild)
    visible = [
        contrib.manifest()
        for contrib in gateway.registry.all()
        if level >= _level_value(contrib.meta.permission)
    ]
    return {"contributions": visible}


@dispatcher.method("widget.data")
async def widget_data(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    key = (params.get("args") or {}).get("key")
    contrib = gateway.registry.get(key)
    if contrib is None or contrib.kind != "widget":
        raise RpcError(INVALID_PARAMS, "Unbekanntes Widget")
    await _require(gateway, ctx, contrib.meta.permission)
    data = await contrib.handler(ctx)
    return {"data": data.to_dict() if hasattr(data, "to_dict") else data}


@dispatcher.method("panel.schema")
async def panel_schema(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    key = (params.get("args") or {}).get("key")
    contrib = gateway.registry.get(key)
    if contrib is None or contrib.kind != "panel":
        raise RpcError(INVALID_PARAMS, "Unbekanntes Panel")
    await _require(gateway, ctx, contrib.meta.permission)
    schema = await contrib.handler(ctx)
    return {"schema": schema.to_dict() if hasattr(schema, "to_dict") else schema}


@dispatcher.method("panel.submit")
async def panel_submit(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    args = params.get("args") or {}
    key = args.get("key")
    data = args.get("data") or {}
    contrib = gateway.registry.get(key)
    if contrib is None or contrib.kind != "panel":
        raise RpcError(INVALID_PARAMS, "Unbekanntes Panel")
    await _require(gateway, ctx, contrib.meta.permission)
    if contrib.submit is None:
        raise RpcError(INVALID_PARAMS, "Panel ist schreibgeschützt (kein on_submit)")
    result = await contrib.submit(ctx, data)
    gateway.audit("panel.submit", ctx, {"key": key})
    return {"result": result.to_dict() if hasattr(result, "to_dict") else result}


@dispatcher.method("page.schema")
async def page_schema(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    key = (params.get("args") or {}).get("key")
    contrib = gateway.registry.get(key)
    if contrib is None or contrib.kind != "page":
        raise RpcError(INVALID_PARAMS, "Unbekannte Seite")
    await _require(gateway, ctx, contrib.meta.permission)
    schema = await contrib.handler(ctx)
    return {"schema": schema.to_dict() if hasattr(schema, "to_dict") else schema}


# --------------------------------------------------------------------------- #
# Cog-Verwaltung (nur Bot-Owner)
# --------------------------------------------------------------------------- #
@dispatcher.method("list.rows")
async def list_rows(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    key = (params.get("args") or {}).get("key")
    contrib = gateway.registry.get(key)
    if contrib is None or contrib.kind != "list":
        raise RpcError(INVALID_PARAMS, "Unbekannte Liste")
    await _require(gateway, ctx, contrib.meta.permission)
    rows = await contrib.handler(ctx)
    return {"rows": rows, "columns": contrib.meta.extra.get("columns", [])}


@dispatcher.method("list.delete")
async def list_delete(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    args = params.get("args") or {}
    key = args.get("key")
    item_id = args.get("id")
    contrib = gateway.registry.get(key)
    if contrib is None or contrib.kind != "list":
        raise RpcError(INVALID_PARAMS, "Unbekannte Liste")
    await _require(gateway, ctx, contrib.meta.permission)
    if contrib.delete is None:
        raise RpcError(INVALID_PARAMS, "Liste ist schreibgeschützt (kein on_delete)")
    result = await contrib.delete(ctx, item_id)
    gateway.audit("list.delete", ctx, {"key": key, "id": item_id})
    return {"result": result.to_dict() if hasattr(result, "to_dict") else result}


@dispatcher.method("list.edit_form")
async def list_edit_form(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    args = params.get("args") or {}
    key = args.get("key")
    item_id = args.get("id")
    contrib = gateway.registry.get(key)
    if contrib is None or contrib.kind != "list":
        raise RpcError(INVALID_PARAMS, "Unbekannte Liste")
    await _require(gateway, ctx, contrib.meta.permission)
    if contrib.edit_form is None:
        raise RpcError(INVALID_PARAMS, "Liste ist nicht bearbeitbar (kein edit_form)")
    schema = await contrib.edit_form(ctx, item_id)
    return {"schema": schema.to_dict() if hasattr(schema, "to_dict") else schema}


@dispatcher.method("list.edit")
async def list_edit(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    args = params.get("args") or {}
    key = args.get("key")
    item_id = args.get("id")
    data = args.get("data") or {}
    contrib = gateway.registry.get(key)
    if contrib is None or contrib.kind != "list":
        raise RpcError(INVALID_PARAMS, "Unbekannte Liste")
    await _require(gateway, ctx, contrib.meta.permission)
    if contrib.edit is None:
        raise RpcError(INVALID_PARAMS, "Liste ist nicht bearbeitbar (kein on_edit)")
    result = await contrib.edit(ctx, item_id, data)
    gateway.audit("list.edit", ctx, {"key": key, "id": item_id})
    return {"result": result.to_dict() if hasattr(result, "to_dict") else result}


@dispatcher.method("cogs.list")
async def cogs_list(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Alle installierten Cogs mit Ladezustand (Owner)."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    bot = gateway.bot
    loaded = set(bot.extensions.keys())  # Paketnamen (klein)
    try:
        available = set(await bot._cog_mgr.available_modules())
    except Exception:
        available = set(loaded)
    contributing = {c.cog_name.lower() for c in gateway.registry.all()}
    names = sorted(available | loaded)
    cogs = [
        {
            "name": name,
            "loaded": name in loaded,
            "has_dashboard": name.lower() in contributing,
        }
        for name in names
    ]
    return {"cogs": cogs, "loaded_count": len(loaded), "total": len(names)}


@dispatcher.method("cogs.set")
async def cogs_set(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Cog laden/entladen/neu laden (Owner). action: load | unload | reload."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    args = params.get("args") or {}
    name = str(args.get("name", "")).strip().lower()
    action = args.get("action")
    if not name or action not in ("load", "unload", "reload"):
        raise RpcError(INVALID_PARAMS, "name/action fehlt oder ungültig")
    bot = gateway.bot

    # Eigenes Paket (das den Gateway betreibt) ermitteln – ein Self-Reload
    # würde den Gateway mitten in der Antwort beenden.
    own_pkg = None
    try:
        dcog = bot.get_cog("WebDashboard")
        if dcog is not None:
            own_pkg = str(type(dcog).__module__).split(".")[0].lower()
    except Exception:
        own_pkg = None

    async def _reload_pkg(pkg: str) -> None:
        # discord.py 2.x: load/unload/reload_extension sind Coroutines → awaiten!
        if pkg in bot.extensions:
            await bot.unload_extension(pkg)
        spec = await bot._cog_mgr.find_cog(pkg)
        if spec is None:
            raise RpcError(INVALID_PARAMS, f"Cog '{pkg}' nicht gefunden")
        await bot.load_extension(spec)
        async with bot._config.packages() as pkgs:
            if pkg not in pkgs:
                pkgs.append(pkg)

    # Self-Reload des Dashboard-Cogs: verzögert ausführen, damit diese Antwort
    # noch rausgeht, bevor der Gateway neu startet.
    if action == "reload" and own_pkg and name == own_pkg:
        import asyncio

        async def _deferred() -> None:
            try:
                await asyncio.sleep(1.0)
                await _reload_pkg(name)
            except Exception:
                logging.getLogger("red.dks.webdashboard.gateway").exception(
                    "Self-Reload von %s fehlgeschlagen", name
                )

        asyncio.ensure_future(_deferred())
        gateway.audit("cogs.reload", ctx, {"name": name, "deferred": True})
        return {"ok": True, "name": name, "deferred": True,
                "hint": "Dashboard startet in ~1s neu – Seite danach neu laden."}

    try:
        if action == "load":
            spec = await bot._cog_mgr.find_cog(name)
            if spec is None:
                raise RpcError(INVALID_PARAMS, f"Cog '{name}' nicht gefunden")
            await bot.load_extension(spec)
            async with bot._config.packages() as pkgs:
                if name not in pkgs:
                    pkgs.append(name)
        elif action == "reload":
            await _reload_pkg(name)
        elif action == "unload":
            if name in bot.extensions:
                await bot.unload_extension(name)
            async with bot._config.packages() as pkgs:
                if name in pkgs:
                    pkgs.remove(name)
    except RpcError:
        raise
    except Exception as e:  # Red-/Import-Fehler sauber durchreichen
        raise RpcError(INTERNAL_ERROR, f"{action} fehlgeschlagen: {e}")

    gateway.audit(f"cogs.{action}", ctx, {"name": name})
    return {"ok": True, "name": name, "loaded": name in bot.extensions}


# --------------------------------------------------------------------------- #
# Slash-/App-Command-Verwaltung (nur Bot-Owner)
# --------------------------------------------------------------------------- #
@dispatcher.method("slash.list")
async def slash_list(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Top-Level-App-Commands mit Cog und Aktiv-Status (Owner)."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    bot = gateway.bot

    items = []
    seen = set()

    try:
        from discord import app_commands  # type: ignore
        ContextMenu = app_commands.ContextMenu
    except Exception:
        app_commands = None  # type: ignore
        ContextMenu = ()  # isinstance(..., ()) ist immer False

    def _ctype(c) -> int:
        try:
            if ContextMenu and isinstance(c, ContextMenu):
                return int(getattr(c, "type").value)  # 2=user, 3=message
        except Exception:
            pass
        return 1  # chat_input / Slash

    # AKTIV-Status: PRIMÄR aus Reds Enabled-Config (spiegelt enable/disable_app_command
    # SOFORT wider, auch ohne Sync). list_enabled_app_commands() ist je nach Red-Version
    # sync ODER async → beides abfangen. FALLBACK: Tree-Mitgliedschaft (Steady-State).
    enabled_keys = set()
    used_cfg = False
    try:
        res = bot.list_enabled_app_commands()
        if hasattr(res, "__await__"):
            res = await res
        if isinstance(res, dict):
            for k, ctype in (("slash", 1), ("user", 2), ("message", 3)):
                for nm in (res.get(k) or {}).keys():
                    enabled_keys.add((nm, ctype))
            used_cfg = True
    except Exception:
        used_cfg = False

    tree_cmds = []
    try:
        tree_cmds = list(bot.tree.get_commands())
        if not used_cfg:
            # Kein Config-Zugriff → Tree als Aktiv-Indikator (Red entfernt deaktivierte
            # App-Commands aus dem Tree).
            for c in tree_cmds:
                enabled_keys.add((getattr(c, "name", None), _ctype(c)))
    except Exception:
        pass

    # Cog für einen Tree-Befehl bestimmen – Binding zuerst, sonst über das Modul.
    def _cog_for(c) -> str:
        b = getattr(c, "binding", None)
        if b is not None:
            return type(b).__name__
        mod = getattr(c, "module", None) or getattr(getattr(c, "callback", None), "__module__", None)
        if mod:
            top = str(mod).split(".")[0]
            for cn, cg in bot.cogs.items():
                try:
                    if str(getattr(type(cg), "__module__", "")).split(".")[0] == top:
                        return cn
                except Exception:
                    continue
        return "—"

    def _add(c, cog_name):
        try:
            name = getattr(c, "name", None)
            if not name:
                return
            ctype = _ctype(c)
            key = (name, ctype)
            if key in seen:
                return
            seen.add(key)
            items.append({
                "name": name,
                "type": ctype,
                "cog": cog_name,
                "enabled": key in enabled_keys,
            })
        except Exception:
            return

    # 1) Alle von Cogs DEFINIERTEN App-Commands – inkl. deaktivierter (nicht im Tree).
    try:
        for cog_name, cog in list(bot.cogs.items()):
            try:
                cmds = []
                if hasattr(cog, "get_app_commands"):
                    cmds = list(cog.get_app_commands())
                elif hasattr(cog, "walk_app_commands"):
                    cmds = list(cog.walk_app_commands())
                cmds += list(getattr(cog, "__cog_context_menus__", []) or [])
                for c in cmds:
                    _add(c, cog_name)
            except Exception:
                continue
    except Exception:
        pass

    # 2) Tree-Befehle ergänzen (mit Modul-Fallback für die Kategorisierung).
    try:
        for c in tree_cmds:
            _add(c, _cog_for(c))
    except Exception:
        pass

    items.sort(key=lambda x: (x["cog"].lower(), x["name"]))
    return {"commands": items, "count": len(items), "managed": True}


@dispatcher.method("slash.sync")
async def slash_sync(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """App-Commands mit Discord synchronisieren (Owner)."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    try:
        synced = await gateway.bot.tree.sync()
        gateway.audit("slash.sync", ctx, {"count": len(synced)})
        return {"ok": True, "count": len(synced)}
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Sync fehlgeschlagen: {e}")


@dispatcher.method("slash.set")
async def slash_set(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Einzelnen App-Command aktivieren/deaktivieren (Owner). Danach synchronisieren."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    args = params.get("args") or {}
    name = str(args.get("name", "")).strip()
    ctype = int(args.get("type", 1) or 1)
    enabled = bool(args.get("enabled"))
    if not name:
        raise RpcError(INVALID_PARAMS, "name erforderlich")
    bot = gateway.bot
    try:
        from discord import AppCommandType

        t = AppCommandType(ctype)
        if enabled:
            await bot.enable_app_command(name, t)
        else:
            await bot.disable_app_command(name, t)
    except RpcError:
        raise
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Umschalten fehlgeschlagen: {e}")
    gateway.audit("slash.set", ctx, {"name": name, "type": ctype, "enabled": enabled})
    return {"ok": True, "name": name, "enabled": enabled}


@dispatcher.method("slash.set_cog")
async def slash_set_cog(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Alle Top-Level-App-Commands eines Cogs aktivieren/deaktivieren (Owner)."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    args = params.get("args") or {}
    cog_name = str(args.get("cog", "")).strip()
    enabled = bool(args.get("enabled"))
    if not cog_name:
        raise RpcError(INVALID_PARAMS, "cog erforderlich")
    bot = gateway.bot
    changed = 0
    try:
        from discord import AppCommandType, app_commands

        for c in bot.tree.get_commands():
            binding = getattr(c, "binding", None)
            if binding is None or type(binding).__name__ != cog_name:
                continue
            ctype = int(c.type.value) if isinstance(c, app_commands.ContextMenu) else 1
            t = AppCommandType(ctype)
            try:
                if enabled:
                    await bot.enable_app_command(c.name, t)
                else:
                    await bot.disable_app_command(c.name, t)
                changed += 1
            except Exception:
                pass
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Cog-Umschalten fehlgeschlagen: {e}")
    gateway.audit("slash.set_cog", ctx, {"cog": cog_name, "enabled": enabled, "changed": changed})
    return {"ok": True, "cog": cog_name, "enabled": enabled, "changed": changed}


# --------------------------------------------------------------------------- #
# Downloader (Repos/Cogs) – nutzt Reds Downloader-Cog (nur Bot-Owner)
# --------------------------------------------------------------------------- #
def _downloader(gateway: Any):
    return gateway.bot.get_cog("Downloader")


def _iter_repos(dl):
    """Repos je nach Red-Version: dict {name: Repo} ODER Tuple/Liste von Repo."""
    repos = dl._repo_manager.repos
    if isinstance(repos, dict):
        return list(repos.values())
    return list(repos)


async def _installed_cogs(dl):
    try:
        return list(await dl.installed_cogs())
    except Exception:
        return []


async def _cogs_with_updates(dl, installed):
    """Namen installierter Cogs, für die ein Update bereitliegt (best effort).

    Nutzt Reds internes ``_available_updates`` (vergleicht installierten Commit mit
    dem aktuellen Repo-Checkout – kein Netzwerk). Schlägt es fehl, leeres Set.
    """
    try:
        result = await dl._available_updates(installed)
        cogs_to_update = result[0] if isinstance(result, (tuple, list)) else result
        return {getattr(c, "name", None) for c in (cogs_to_update or [])}
    except Exception:
        return set()


async def _update_all_repos(dl):
    """Aktualisiert alle Repos versions-robust und liefert die Namen geänderter Repos."""
    before = {r.name: getattr(r, "commit", None) for r in _iter_repos(dl)}
    rm = dl._repo_manager
    # Neuere Red-Versionen: update_all_repos(); ältere: pro Repo Repo.update().
    if hasattr(rm, "update_all_repos"):
        await rm.update_all_repos()
    else:
        for repo in _iter_repos(dl):
            try:
                await repo.update()
            except Exception:
                continue
    return [r.name for r in _iter_repos(dl) if before.get(r.name) != getattr(r, "commit", None)]


@dispatcher.method("downloader.repos")
async def downloader_repos(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Repos mit installierten und verfügbaren Cogs (Owner)."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    dl = _downloader(gateway)
    if dl is None:
        return {"available": False, "repos": []}
    try:
        installed = await _installed_cogs(dl)
        update_names = await _cogs_with_updates(dl, installed)
        by_repo: Dict[str, list] = {}
        for m in installed:
            by_repo.setdefault(getattr(m, "repo_name", "?"), []).append({
                "name": m.name, "commit": getattr(m, "commit", None),
                "update_available": m.name in update_names,
            })
        repos = []
        for repo in _iter_repos(dl):
            avail = [
                {"name": inst.name, "description": (getattr(inst, "short", "") or "").strip()}
                for inst in getattr(repo, "available_cogs", [])
                if not getattr(inst, "hidden", False)
            ]
            repos.append({
                "name": repo.name,
                "url": getattr(repo, "url", None),
                "branch": getattr(repo, "branch", None),
                "commit": getattr(repo, "commit", None),
                "installed": sorted(by_repo.get(repo.name, []), key=lambda x: x["name"]),
                "available_cogs": sorted(avail, key=lambda x: x["name"]),
            })
        repos.sort(key=lambda r: r["name"])
        return {"available": True, "repos": repos}
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Repo-Liste fehlgeschlagen: {e}")


@dispatcher.method("downloader.repo_add")
async def downloader_repo_add(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    dl = _downloader(gateway)
    if dl is None:
        raise RpcError(INVALID_PARAMS, "Downloader-Cog ist nicht geladen")
    args = params.get("args") or {}
    name = str(args.get("name", "")).strip()
    url = str(args.get("url", "")).strip()
    branch = (args.get("branch") or None) or None
    if not name or not url:
        raise RpcError(INVALID_PARAMS, "name und url erforderlich")
    try:
        await dl._repo_manager.add_repo(url=url, name=name, branch=branch)
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Repo hinzufügen fehlgeschlagen: {e}")
    gateway.audit("downloader.repo_add", ctx, {"name": name, "url": url})
    return {"ok": True, "name": name}


@dispatcher.method("downloader.repo_remove")
async def downloader_repo_remove(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    dl = _downloader(gateway)
    if dl is None:
        raise RpcError(INVALID_PARAMS, "Downloader-Cog ist nicht geladen")
    name = str((params.get("args") or {}).get("name", "")).strip()
    if not name:
        raise RpcError(INVALID_PARAMS, "name erforderlich")
    # Schutz: nur entfernen, wenn keine Cogs aus diesem Repo mehr installiert sind.
    installed = await _installed_cogs(dl)
    if any(getattr(m, "repo_name", None) == name for m in installed):
        raise RpcError(INVALID_PARAMS, "Repo hat noch installierte Cogs – diese zuerst deinstallieren.")
    try:
        await dl._repo_manager.delete_repo(name)
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Repo entfernen fehlgeschlagen: {e}")
    gateway.audit("downloader.repo_remove", ctx, {"name": name})
    return {"ok": True}


@dispatcher.method("downloader.update_check")
async def downloader_update_check(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Aktualisiert die Repos (git fetch/pull) und meldet, was sich geändert hat."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    dl = _downloader(gateway)
    if dl is None:
        raise RpcError(INVALID_PARAMS, "Downloader-Cog ist nicht geladen")
    try:
        changed = await _update_all_repos(dl)
        # Nach dem Repo-Update: welche installierten Cogs haben jetzt ein Update?
        installed = await _installed_cogs(dl)
        cogs_update = sorted(await _cogs_with_updates(dl, installed))
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Update-Check fehlgeschlagen: {e}")
    gateway.audit("downloader.update_check", ctx, {"changed": changed, "cogs": cogs_update})
    return {"ok": True, "updated_repos": changed, "cogs_with_updates": cogs_update}


@dispatcher.method("downloader.cog_update")
async def downloader_cog_update(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Einen installierten Cog auf den neuesten Stand des Repos bringen (Owner)."""
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    dl = _downloader(gateway)
    if dl is None:
        raise RpcError(INVALID_PARAMS, "Downloader-Cog ist nicht geladen")
    cog_name = str((params.get("args") or {}).get("cog", "")).strip()
    if not cog_name:
        raise RpcError(INVALID_PARAMS, "cog erforderlich")
    try:
        installed = await _installed_cogs(dl)
        target = next((m for m in installed if m.name == cog_name), None)
        if target is None:
            raise RpcError(INVALID_PARAMS, f"Cog '{cog_name}' ist nicht installiert")
        # WICHTIG: NICHT den Install-Pfad (_filter_incorrect_cogs_by_names) nutzen –
        # der lehnt bereits installierte Cogs ab ("bereits installiert"). Für ein
        # Update das Installable direkt neu installieren (überschreibt die Dateien).
        cog_obj = None
        try:
            res = await dl._available_updates(installed)
            updatable = res[0] if isinstance(res, (tuple, list)) else res
            cog_obj = next((c for c in (updatable or []) if getattr(c, "name", None) == cog_name), None)
        except Exception:
            cog_obj = None
        if cog_obj is None:
            # Kein erkanntes Update mehr → direkt aus dem (aktualisierten) Repo-Checkout holen.
            repo = dl._repo_manager.get_repo(getattr(target, "repo_name", ""))
            if repo is None:
                raise RpcError(INVALID_PARAMS, "Zugehöriges Repo nicht gefunden")
            cog_obj = next(
                (c for c in getattr(repo, "available_cogs", []) if getattr(c, "name", None) == cog_name),
                None,
            )
        if cog_obj is None:
            raise RpcError(INVALID_PARAMS, f"Cog '{cog_name}' nicht im Repo gefunden")
        installed_cogs, failed = await dl._install_cogs([cog_obj])
        if hasattr(dl, "_save_to_installed"):
            await dl._save_to_installed(installed_cogs)
        if failed:
            raise RpcError(INTERNAL_ERROR, f"Update fehlgeschlagen: {cog_name}")
    except RpcError:
        raise
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Update fehlgeschlagen: {e}")
    gateway.audit("downloader.cog_update", ctx, {"cog": cog_name})
    return {"ok": True, "cog": cog_name, "hint": f"Mit [p]reload {cog_name} neu laden."}


@dispatcher.method("downloader.cog_install")
async def downloader_cog_install(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    dl = _downloader(gateway)
    if dl is None:
        raise RpcError(INVALID_PARAMS, "Downloader-Cog ist nicht geladen")
    args = params.get("args") or {}
    repo_name = str(args.get("repo", "")).strip()
    cog_name = str(args.get("cog", "")).strip()
    if not repo_name or not cog_name:
        raise RpcError(INVALID_PARAMS, "repo und cog erforderlich")
    try:
        repo = dl._repo_manager.get_repo(repo_name)
        if repo is None:
            raise RpcError(INVALID_PARAMS, f"Repo '{repo_name}' nicht gefunden")
        cogs, message = await dl._filter_incorrect_cogs_by_names(repo, [cog_name])
        if not cogs:
            raise RpcError(INVALID_PARAMS, message or f"Cog '{cog_name}' nicht im Repo")
        installed_cogs, failed = await dl._install_cogs(cogs)
        if hasattr(dl, "_save_to_installed"):
            await dl._save_to_installed(installed_cogs)
        if failed:
            raise RpcError(INTERNAL_ERROR, f"Installation fehlgeschlagen: {cog_name}")
    except RpcError:
        raise
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Installation fehlgeschlagen: {e}")
    gateway.audit("downloader.cog_install", ctx, {"repo": repo_name, "cog": cog_name})
    return {"ok": True, "cog": cog_name, "hint": "Mit cogs.set/load aktivieren."}


@dispatcher.method("downloader.cog_uninstall")
async def downloader_cog_uninstall(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    dl = _downloader(gateway)
    if dl is None:
        raise RpcError(INVALID_PARAMS, "Downloader-Cog ist nicht geladen")
    cog_name = str((params.get("args") or {}).get("cog", "")).strip()
    if not cog_name:
        raise RpcError(INVALID_PARAMS, "cog erforderlich")
    bot = gateway.bot
    # 1) Slash-Commands abschalten: durch Entladen verschwinden die App-Commands
    #    aus dem Tree; anschließend wird synchronisiert.
    try:
        if cog_name.lower() in bot.extensions:
            bot.unload_extension(cog_name.lower())
        async with bot._config.packages() as pkgs:
            if cog_name.lower() in pkgs:
                pkgs.remove(cog_name.lower())
    except Exception:
        pass
    # 2) Dateien/Installation entfernen
    try:
        installed = await _installed_cogs(dl)
        target = [m for m in installed if m.name == cog_name]
        if not target:
            raise RpcError(INVALID_PARAMS, f"'{cog_name}' ist nicht installiert")
        if hasattr(dl, "_remove_from_installed"):
            await dl._remove_from_installed(target)
        if hasattr(dl, "_delete_cog"):
            for m in target:
                await dl._delete_cog(m.name)
    except RpcError:
        raise
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Deinstallation fehlgeschlagen: {e}")
    # 3) Tree synchronisieren (Slash sauber abmelden)
    try:
        await bot.tree.sync()
    except Exception:
        pass
    gateway.audit("downloader.cog_uninstall", ctx, {"cog": cog_name})
    return {"ok": True, "cog": cog_name}


# --------------------------------------------------------------------------- #
# Bot-Settings (Reds Prefixe/Rollen/Nick/Embeds) – global & pro Guild
# --------------------------------------------------------------------------- #
@dispatcher.method("settings.get")
async def settings_get(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    bot = gateway.bot
    scope = (params.get("args") or {}).get("scope", "guild")

    if scope == "global":
        await _require(gateway, ctx, "bot_owner")
        return {
            "scope": "global",
            "prefixes": list(await bot._config.prefix()),
            "embeds": await bot._config.embeds(),
            "fuzzy": await bot._config.fuzzy(),
        }

    if ctx.guild is None:
        raise RpcError(INVALID_PARAMS, "Guild-Kontext erforderlich")
    await _require(gateway, ctx, "guild_admin")
    g = ctx.guild
    me = g.me
    return {
        "scope": "guild",
        "guild_id": str(g.id),
        "global_prefixes": list(await bot._config.prefix()),
        "guild_prefixes": list(await bot._config.guild(g).prefix()),
        "nickname": (me.nick if me else None),
        "admin_roles": [str(r) for r in await bot._config.guild(g).admin_role()],
        "mod_roles": [str(r) for r in await bot._config.guild(g).mod_role()],
        "embeds": await bot._config.guild(g).embeds(),
        "roles": [
            {"id": str(r.id), "name": r.name}
            for r in sorted(g.roles, key=lambda r: r.position, reverse=True)
            if not r.is_default()
        ],
    }


@dispatcher.method("settings.set")
async def settings_set(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    bot = gateway.bot
    args = params.get("args") or {}
    scope = args.get("scope", "guild")
    field = args.get("field")
    value = args.get("value")

    try:
        if scope == "global":
            await _require(gateway, ctx, "bot_owner")
            if field == "prefixes":
                prefixes = [str(p) for p in (value or []) if str(p).strip()]
                if not prefixes:
                    raise RpcError(INVALID_PARAMS, "Mindestens ein globaler Prefix nötig")
                await bot.set_prefixes(prefixes, guild=None)
            elif field == "embeds":
                await bot._config.embeds.set(bool(value))
            elif field == "fuzzy":
                await bot._config.fuzzy.set(bool(value))
            else:
                raise RpcError(INVALID_PARAMS, f"Unbekanntes Feld '{field}'")
            gateway.audit("settings.set", ctx, {"scope": scope, "field": field})
            return {"ok": True}

        if ctx.guild is None:
            raise RpcError(INVALID_PARAMS, "Guild-Kontext erforderlich")
        await _require(gateway, ctx, "guild_admin")
        g = ctx.guild
        if field == "prefixes":
            await bot.set_prefixes([str(p) for p in (value or []) if str(p).strip()], guild=g)
        elif field == "nickname":
            await g.me.edit(nick=(str(value) or None) if value else None)
        elif field == "admin_roles":
            await bot._config.guild(g).admin_role.set([int(x) for x in (value or [])])
        elif field == "mod_roles":
            await bot._config.guild(g).mod_role.set([int(x) for x in (value or [])])
        elif field == "embeds":
            await bot._config.guild(g).embeds.set(None if value is None else bool(value))
        else:
            raise RpcError(INVALID_PARAMS, f"Unbekanntes Feld '{field}'")
    except RpcError:
        raise
    except Exception as e:
        raise RpcError(INTERNAL_ERROR, f"Speichern fehlgeschlagen: {e}")

    gateway.audit("settings.set", ctx, {"scope": scope, "field": field})
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Dashboard-Branding, Overview, Lock, Sessions, Custom Pages
# --------------------------------------------------------------------------- #
def _dashboard_cog(gateway: Any):
    return gateway.bot.get_cog("WebDashboard")


@dispatcher.method("dashboard.branding")
async def dashboard_branding(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Öffentliches Branding (Titel/Icon/Theme) – ohne Login nutzbar."""
    cog = _dashboard_cog(gateway)
    ui = (await cog.config.ui()) if cog else {}
    locked = bool(await cog.config.locked()) if cog else False
    return {"ui": ui, "locked": locked}


@dispatcher.method("dashboard.overview")
async def dashboard_overview(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)  # authentifiziert genügt
    bot = gateway.bot
    cog = _dashboard_cog(gateway)

    bot_uptime = None
    up = getattr(bot, "uptime", None)
    if up is not None:
        try:
            now = datetime.now(up.tzinfo) if getattr(up, "tzinfo", None) else datetime.utcnow()
            bot_uptime = int((now - up).total_seconds())
        except Exception:
            bot_uptime = None

    gw_uptime = None
    if getattr(gateway, "started_at", None):
        gw_uptime = int(time.time() - gateway.started_at)

    return {
        "bot_name": bot.user.name if bot.user else None,
        "bot_avatar": str(bot.user.display_avatar.url) if bot.user else None,
        "guild_count": len(bot.guilds),
        "user_count": len(bot.users),
        "loaded_cogs": len(bot.cogs),
        "contributions": len(gateway.registry.all()),
        "bot_uptime_s": bot_uptime,
        "gateway_uptime_s": gw_uptime,
        "locked": bool(await cog.config.locked()) if cog else False,
        "is_owner": await bot.is_owner(ctx.user),
    }


@dispatcher.method("dashboard.settings_get")
async def dashboard_settings_get(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    cog = _dashboard_cog(gateway)
    return {"ui": await cog.config.ui(), "locked": await cog.config.locked()}


@dispatcher.method("dashboard.settings_set")
async def dashboard_settings_set(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    cog = _dashboard_cog(gateway)
    ui = dict(await cog.config.ui())
    incoming = (params.get("args") or {}).get("ui") or {}
    for k in ("title", "icon", "description", "support_url", "color", "theme"):
        if k in incoming:
            ui[k] = incoming[k]
    await cog.config.ui.set(ui)
    gateway.audit("dashboard.settings_set", ctx, {})
    return {"ok": True, "ui": ui}


@dispatcher.method("dashboard.lock")
async def dashboard_lock(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    cog = _dashboard_cog(gateway)
    value = bool((params.get("args") or {}).get("locked"))
    await cog.config.locked.set(value)
    gateway.audit("dashboard.lock", ctx, {"locked": value})
    return {"ok": True, "locked": value}


@dispatcher.method("dashboard.refresh_sessions")
async def dashboard_refresh_sessions(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    cog = _dashboard_cog(gateway)
    epoch = time.time()
    await cog.config.session_epoch.set(epoch)
    gateway.audit("dashboard.refresh_sessions", ctx, {})
    return {"ok": True, "epoch": epoch}


@dispatcher.method("dashboard.session_epoch")
async def dashboard_session_epoch(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Aktueller Session-Epoch (vom BFF zur Invalidierung genutzt)."""
    cog = _dashboard_cog(gateway)
    return {"epoch": float(await cog.config.session_epoch()) if cog else 0.0}


# ----- Custom Pages -------------------------------------------------------- #
@dispatcher.method("pages.list")
async def pages_list(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Öffentliche Liste der Custom Pages (ohne HTML, für Navigation)."""
    cog = _dashboard_cog(gateway)
    pages = list(await cog.config.custom_pages()) if cog else []
    return {"pages": [{
        "slug": p["slug"],
        "title": p["title"],
        "nav": p.get("nav", True),
        "visibility": p.get("visibility", "public"),
    } for p in pages]}


@dispatcher.method("pages.get")
async def pages_get(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    cog = _dashboard_cog(gateway)
    slug = str((params.get("args") or {}).get("slug", ""))
    pages = list(await cog.config.custom_pages()) if cog else []
    for p in pages:
        if p["slug"] == slug:
            return {"page": p}
    raise RpcError(INVALID_PARAMS, "Seite nicht gefunden")


@dispatcher.method("pages.save")
async def pages_save(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    cog = _dashboard_cog(gateway)
    args = params.get("args") or {}
    slug = str(args.get("slug", "")).strip().lower().replace(" ", "-")
    if not slug:
        raise RpcError(INVALID_PARAMS, "slug erforderlich")
    visibility = "private" if str(args.get("visibility", "public")).lower() == "private" else "public"
    entry = {
        "slug": slug,
        "title": str(args.get("title", slug)),
        # Inhalt wird als Markdown gespeichert; `html` bleibt als Legacy-Fallback erhalten.
        "markdown": str(args.get("markdown", "")),
        "html": str(args.get("html", "")),
        "nav": bool(args.get("nav", True)),
        "visibility": visibility,
    }
    async with cog.config.custom_pages() as pages:
        for i, p in enumerate(pages):
            if p["slug"] == slug:
                pages[i] = entry
                break
        else:
            pages.append(entry)
    gateway.audit("pages.save", ctx, {"slug": slug})
    return {"ok": True, "slug": slug}


@dispatcher.method("pages.delete")
async def pages_delete(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    cog = _dashboard_cog(gateway)
    slug = str((params.get("args") or {}).get("slug", ""))
    async with cog.config.custom_pages() as pages:
        pages[:] = [p for p in pages if p["slug"] != slug]
    gateway.audit("pages.delete", ctx, {"slug": slug})
    return {"ok": True}


# ----- Server-Statistiken (WebServerStats-Cog) ----------------------------- #
def _serverstats(gateway: Any):
    bot = gateway.bot
    cog = bot.get_cog("WebServerStats")
    if cog is not None:
        return cog
    # Fallback: Cog über Klassennamen oder Modul (web_serverstats) finden,
    # falls der qualifizierte Name abweicht.
    for c in bot.cogs.values():
        try:
            if type(c).__name__ == "WebServerStats":
                return c
            if str(getattr(type(c), "__module__", "")).split(".")[0] == "web_serverstats":
                return c
        except Exception:
            continue
    return None


async def _stats_call(gateway: Any, params: Dict[str, Any], method_name: str, *extra_keys):
    """Gemeinsamer Helfer: Kontext + Recht + Cog-Methode aufrufen."""
    ctx = await _build_context(gateway, params)
    if ctx.guild is None:
        raise RpcError(INVALID_PARAMS, "Unbekannte Guild")
    await _require(gateway, ctx, "guild_member")
    cog = _serverstats(gateway)
    if cog is None:
        raise RpcError(INVALID_PARAMS, "WebServerStats-Cog ist nicht geladen")
    args = params.get("args") or {}
    days = int(args.get("days", 30) or 30)
    fn = getattr(cog, method_name)
    call_args = [ctx.guild]
    for k in extra_keys:
        call_args.append(args.get(k))
    call_args.append(days)
    return await fn(*call_args)


@dispatcher.method("serverstats.overview")
async def serverstats_overview(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _stats_call(gateway, params, "stats_overview")


@dispatcher.method("serverstats.messages")
async def serverstats_messages(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _stats_call(gateway, params, "stats_messages")


@dispatcher.method("serverstats.voice")
async def serverstats_voice(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _stats_call(gateway, params, "stats_voice")


@dispatcher.method("serverstats.status")
async def serverstats_status(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _stats_call(gateway, params, "stats_status")


@dispatcher.method("serverstats.invites")
async def serverstats_invites(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _stats_call(gateway, params, "stats_invites")


@dispatcher.method("serverstats.activity")
async def serverstats_activity(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _stats_call(gateway, params, "stats_activity")


@dispatcher.method("serverstats.member_drilldown")
async def serverstats_member_drilldown(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    args = params.get("args") or {}
    mid = args.get("member_id")
    member_id = int(mid) if mid and str(mid).isdigit() else 0
    ctx = await _build_context(gateway, params)
    if ctx.guild is None:
        raise RpcError(INVALID_PARAMS, "Unbekannte Guild")
    await _require(gateway, ctx, "guild_member")
    cog = _serverstats(gateway)
    if cog is None:
        raise RpcError(INVALID_PARAMS, "WebServerStats-Cog ist nicht geladen")
    return await cog.stats_member_drilldown(ctx.guild, member_id, int(args.get("days", 30) or 30))


@dispatcher.method("serverstats.channel_drilldown")
async def serverstats_channel_drilldown(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    args = params.get("args") or {}
    cid = args.get("channel_id")
    channel_id = int(cid) if cid and str(cid).isdigit() else 0
    ctx = await _build_context(gateway, params)
    if ctx.guild is None:
        raise RpcError(INVALID_PARAMS, "Unbekannte Guild")
    await _require(gateway, ctx, "guild_member")
    cog = _serverstats(gateway)
    if cog is None:
        raise RpcError(INVALID_PARAMS, "WebServerStats-Cog ist nicht geladen")
    return await cog.stats_channel_drilldown(ctx.guild, channel_id, int(args.get("days", 30) or 30))


def _maybe_integration_base():
    from ..integration.base import DashboardIntegration
    return DashboardIntegration


def setup_core_methods(gateway: Any) -> Dispatcher:
    """Liefert den vorbereiteten Dispatcher (Core-Methoden bereits registriert)."""
    return dispatcher
