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
from typing import Any, Dict, Optional

from ..integration.context import DashboardContext
from ..permissions import _level_value, has_permission, resolve_level
from .rpc import FORBIDDEN, INVALID_PARAMS, UNAUTHORIZED, Dispatcher, RpcError

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
@dispatcher.method("cogs.list")
async def cogs_list(gateway: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await _build_context(gateway, params)
    await _require(gateway, ctx, "bot_owner")
    bot = gateway.bot
    loaded = set(bot.extensions.keys())
    # Cogs, die tatsächlich Beiträge registriert haben (Mixin ODER Drop-in-Pattern)
    contributing = {c.cog_name for c in gateway.registry.all()}
    base = _maybe_integration_base()
    cogs = []
    for name, cog in bot.cogs.items():
        cogs.append({
            "name": name,
            "loaded": True,
            "has_dashboard": name in contributing or isinstance(cog, base),
        })
    return {"cogs": cogs, "loaded_extensions": sorted(loaded)}


def _maybe_integration_base():
    from ..integration.base import DashboardIntegration
    return DashboardIntegration


def setup_core_methods(gateway: Any) -> Dispatcher:
    """Liefert den vorbereiteten Dispatcher (Core-Methoden bereits registriert)."""
    return dispatcher
