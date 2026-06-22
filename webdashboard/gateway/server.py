"""aiohttp-basiertes RPC-Gateway.

- WebSocket ``/rpc``  : JSON-RPC 2.0 (Request/Response + Server-Push für Streams)
- REST ``/api/health``: Liveness ohne Auth
- REST ``/api/manifest``: bequemer GET-Spiegel von ``manifest.get``

Auth zwischen BFF und Gateway über ein geteiltes Secret (konstant-Zeit-Vergleich).
Standardbindung: 127.0.0.1 (nur localhost).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional, Set

from aiohttp import WSMsgType, web

from .methods import dispatcher
from .rpc import UNAUTHORIZED

log = logging.getLogger("red.dks.webdashboard.gateway")


class Gateway:
    def __init__(self, bot: Any, registry: Any, *, token: str, host: str = "127.0.0.1",
                 port: int = 6970, audit_sink=None) -> None:
        self.bot = bot
        self.registry = registry
        self.token = token
        self.host = host
        self.port = port
        self._audit_sink = audit_sink

        self.app = web.Application(middlewares=[self._auth_middleware])
        self.app.add_routes([
            web.get("/api/health", self._health),
            web.get("/api/manifest", self._manifest_rest),
            web.post("/rpc", self._rpc_post),   # Request/Response (BFF)
            web.get("/rpc", self._ws_handler),  # Streams/Push (Live-Logs, Stats)
        ])
        self._runner: Optional[web.AppRunner] = None
        self._ws_clients: Set[web.WebSocketResponse] = set()
        # Channel-Abos: channel -> set(ws)
        self._subscriptions: Dict[str, Set[web.WebSocketResponse]] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        log.info("RPC-Gateway läuft auf http://%s:%s", self.host, self.port)

    async def stop(self) -> None:
        for ws in list(self._ws_clients):
            try:
                await ws.close()
            except Exception:
                pass
        if self._runner is not None:
            await self._runner.cleanup()
        log.info("RPC-Gateway gestoppt")

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #
    def _check_token(self, provided: Optional[str]) -> bool:
        if not provided or not self.token:
            return False
        return hmac.compare_digest(provided, self.token)

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        if request.path == "/api/health":
            return await handler(request)
        # NUR der WebSocket-Upgrade (GET /rpc) authentifiziert sich im
        # connection_init-Frame. POST /rpc (Request/Response) MUSS das Token tragen.
        if request.path == "/rpc" and request.method == "GET":
            return await handler(request)
        if not self._check_token(request.headers.get("X-Dashboard-Token")):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    # ------------------------------------------------------------------ #
    # REST
    # ------------------------------------------------------------------ #
    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "bot_ready": self.bot.is_ready(),
            "time": time.time(),
        })

    async def _manifest_rest(self, request: web.Request) -> web.Response:
        # auth bereits via Middleware; User-Kontext über Query/Header
        user_id = request.headers.get("X-User-Id")
        guild_id = request.headers.get("X-Guild-Id")
        params = {"auth": {"user_id": user_id, "guild_id": guild_id}}
        result = await dispatcher.dispatch(self, {
            "jsonrpc": "2.0", "id": 1, "method": "manifest.get", "params": params,
        })
        return web.json_response(result)

    async def _rpc_post(self, request: web.Request) -> web.Response:
        """HTTP-Variante des JSON-RPC-Dispatchers (Request/Response).

        Erwartet einen einzelnen JSON-RPC-2.0-Request im Body. Auth via Middleware.
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "parse error"}}, status=400)
        if isinstance(data, list):  # Batch
            results = [r for r in
                       [await dispatcher.dispatch(self, m) for m in data] if r is not None]
            return web.json_response(results)
        response = await dispatcher.dispatch(self, data)
        return web.json_response(response if response is not None else {})

    # ------------------------------------------------------------------ #
    # WebSocket / JSON-RPC
    # ------------------------------------------------------------------ #
    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        authenticated = False
        self._ws_clients.add(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "parse error"}})
                    continue

                # erster Frame muss connection_init mit Token sein
                if not authenticated:
                    if data.get("method") == "connection_init" and \
                            self._check_token((data.get("params") or {}).get("token")):
                        authenticated = True
                        await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                            "result": {"ok": True}})
                        continue
                    await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                        "error": {"code": UNAUTHORIZED, "message": "unauthorized"}})
                    await ws.close()
                    break

                # Abo-Steuerung für Push-Streams
                method = data.get("method")
                if method == "subscribe":
                    channel = (data.get("params") or {}).get("channel")
                    self._subscriptions.setdefault(channel, set()).add(ws)
                    await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                        "result": {"subscribed": channel}})
                    continue
                if method == "unsubscribe":
                    channel = (data.get("params") or {}).get("channel")
                    self._subscriptions.get(channel, set()).discard(ws)
                    await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                        "result": {"unsubscribed": channel}})
                    continue

                response = await dispatcher.dispatch(self, data)
                if response is not None:
                    await ws.send_json(response)
        finally:
            self._ws_clients.discard(ws)
            for subs in self._subscriptions.values():
                subs.discard(ws)
        return ws

    # ------------------------------------------------------------------ #
    # Push / Streams (z. B. Live-Logs, Stats)
    # ------------------------------------------------------------------ #
    async def publish(self, channel: str, payload: Any) -> None:
        """Sendet eine Notification an alle Abonnenten eines Channels."""
        subs = self._subscriptions.get(channel)
        if not subs:
            return
        message = {"jsonrpc": "2.0", "method": "stream", "params":
                   {"channel": channel, "data": payload}}
        dead = []
        for ws in subs:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            subs.discard(ws)

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def audit(self, action: str, ctx: Any, detail: Dict[str, Any]) -> None:
        entry = {
            "action": action,
            "user": str(getattr(ctx.user, "id", None)),
            "guild": str(getattr(ctx.guild, "id", None)) if ctx.guild else None,
            "detail": detail,
            "time": time.time(),
        }
        log.info("AUDIT %s", entry)
        if self._audit_sink is not None:
            try:
                asyncio.create_task(self._audit_sink(entry))
            except Exception:
                pass
