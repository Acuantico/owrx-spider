"""HTTP server: public spot WebSocket, admin page and its JSON API."""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import mimetypes
import os
import ssl
import time
from http import HTTPStatus
from typing import Any, Deque, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

from . import __version__, websocket
from .auth import Authenticator
from .config import Config
from .sources import SourceRunner

log = logging.getLogger("spiderd.server")

ADMIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin")
ADMIN_FILES = {"index.html", "admin.js", "admin.css"}
COOKIE = "spider_session"
MAX_HEADER = 16 * 1024
MAX_BODY = 64 * 1024
BACKLOG_LIMIT = 400


class LogBuffer(logging.Handler):
    """Last log lines, shown on the admin page."""

    def __init__(self, size: int = 200) -> None:
        super().__init__(logging.INFO)
        self.lines: Deque[Dict[str, Any]] = collections.deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append({"time": int(record.created), "level": record.levelname,
                               "message": record.getMessage()})
        except Exception:
            pass


class Request:
    def __init__(self, method: str, target: str, headers: Dict[str, str], body: bytes, client: str) -> None:
        self.method = method
        self.path = urlsplit(target).path
        self.headers = headers
        self.body = body
        self.client = client

    def cookie(self, name: str) -> Optional[str]:
        for part in self.headers.get("cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8") or "null")
        except ValueError:
            return None


class SpiderServer:
    def __init__(self, config: Config, auth: Authenticator, log_buffer: LogBuffer) -> None:
        self.config = config
        self.auth = auth
        self.log_buffer = log_buffer
        self.clients: Set[websocket.WebSocket] = set()
        self.recent: Deque[Dict[str, Any]] = collections.deque(maxlen=2000)
        self.source = SourceRunner(self.publish)
        self.started = time.time()
        self.tls = False
        self._server: Optional[asyncio.AbstractServer] = None
        self._pinger: Optional[asyncio.Task] = None

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        srv = self.config["server"]
        ssl_ctx = None
        if srv.get("tls_cert") and srv.get("tls_key"):
            ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_ctx.load_cert_chain(srv["tls_cert"], srv["tls_key"])
            self.tls = True
        self._server = await asyncio.start_server(self._handle, srv["bind"], int(srv["port"]), ssl=ssl_ctx)
        scheme = "https" if self.tls else "http"
        log.info("spiderd %s listening on %s://%s:%s (admin page: /admin/, spots: /spots)",
                 __version__, scheme, srv["bind"], srv["port"])
        self._pinger = asyncio.ensure_future(self._ping_clients())
        await self.source.restart(self.config.data)

    async def stop(self) -> None:
        await self.source.stop()
        if self._pinger:
            self._pinger.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for ws in list(self.clients):
            await ws.close(1001)

    # -- spot fan-out ------------------------------------------------------

    async def publish(self, spot: Dict[str, Any]) -> None:
        self.recent.append(spot)
        await self._broadcast({"type": "spot", "spot": spot})

    async def _broadcast(self, message: Dict[str, Any]) -> None:
        if not self.clients:
            return
        text = json.dumps(message, separators=(",", ":"))
        clients = list(self.clients)
        results = await asyncio.gather(
            *(asyncio.wait_for(ws.send_text(text), 5) for ws in clients), return_exceptions=True
        )
        for ws, result in zip(clients, results):
            if isinstance(result, BaseException):
                self.clients.discard(ws)
                await ws.close(1011)

    def backlog(self) -> List[Dict[str, Any]]:
        """Recent spots still within the display lifetime, newest per call/QRG."""
        cutoff = time.time() - self.config["display"]["max_age_sec"]
        seen = set()
        out = []
        for spot in reversed(self.recent):
            if spot["time"] < cutoff:
                continue
            key = (spot["call"], spot["freq"] // 1000)
            if key in seen:
                continue
            seen.add(key)
            out.append(spot)
            if len(out) >= BACKLOG_LIMIT:
                break
        out.reverse()
        return out

    async def _ping_clients(self) -> None:
        while True:
            await asyncio.sleep(30)
            for ws in list(self.clients):
                try:
                    await asyncio.wait_for(ws.ping(), 5)
                except Exception:
                    self.clients.discard(ws)

    async def _spot_stream(self, ws: websocket.WebSocket) -> None:
        self.clients.add(ws)
        log.debug("browser connected from %s (%d total)", ws.peer, len(self.clients))
        try:
            await ws.send_text(json.dumps({"type": "config", "config": self.config.public()}))
            if self.config["enabled"]:
                await ws.send_text(json.dumps({"type": "spots", "spots": self.backlog()},
                                              separators=(",", ":")))
            while True:
                await ws.recv()  # browsers send nothing; this detects the close
        except (websocket.WebSocketError, ConnectionError):
            pass
        finally:
            self.clients.discard(ws)
            await ws.close()

    # -- HTTP --------------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        client = peer[0] if peer else "?"
        try:
            request = await asyncio.wait_for(self._read_request(reader, client), 15)
        except (asyncio.TimeoutError, ValueError, ConnectionError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError):
            writer.close()
            return
        try:
            if request.path == "/spots" and request.headers.get("upgrade", "").lower() == "websocket":
                ws = await websocket.server_handshake(reader, writer, request.headers)
                await self._spot_stream(ws)
                return
            status, headers, body = await self._route(request)
        except Exception:
            log.exception("error handling %s %s", request.method, request.path)
            status, headers, body = self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})
        try:
            self._write_response(writer, status, headers, body)
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def _read_request(self, reader: asyncio.StreamReader, client: str) -> Request:
        raw = await reader.readuntil(b"\r\n\r\n")
        if len(raw) > MAX_HEADER:
            raise ValueError("headers too large")
        lines = raw.decode("latin-1").split("\r\n")
        method, target, _version = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length") or 0)
        if length > MAX_BODY:
            raise ValueError("body too large")
        body = await reader.readexactly(length) if length else b""
        return Request(method.upper(), target, headers, body, client)

    def _write_response(self, writer: asyncio.StreamWriter, status: HTTPStatus,
                        headers: Dict[str, str], body: bytes) -> None:
        base = {
            "Content-Length": str(len(body)),
            "Connection": "close",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
        }
        base.update(headers)
        head = "HTTP/1.1 %d %s\r\n" % (status.value, status.phrase)
        head += "".join("%s: %s\r\n" % item for item in base.items())
        writer.write(head.encode("latin-1") + b"\r\n" + body)

    @staticmethod
    def _json(status: HTTPStatus, payload: Any, headers: Optional[Dict[str, str]] = None
              ) -> Tuple[HTTPStatus, Dict[str, str], bytes]:
        out = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}
        out.update(headers or {})
        return status, out, json.dumps(payload).encode("utf-8")

    def _session_cookie(self, token: str, max_age: int) -> str:
        cookie = "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (COOKIE, token, max_age)
        return cookie + ("; Secure" if self.tls else "")

    async def _route(self, req: Request) -> Tuple[HTTPStatus, Dict[str, str], bytes]:
        path, method = req.path, req.method

        if path == "/health" and method == "GET":
            return self._json(HTTPStatus.OK, {"ok": True, "version": __version__})
        # Relative redirects and URLs keep the page usable behind a reverse
        # proxy that publishes spiderd under a sub-path (e.g. /spider/).
        if path == "/" and method == "GET":
            return HTTPStatus.FOUND, {"Location": "admin/"}, b""
        if path == "/admin" and method == "GET":
            return HTTPStatus.FOUND, {"Location": "admin/"}, b""
        if not path.startswith("/admin/api/"):
            if path.startswith("/admin/") and method == "GET":
                return self._static(path[len("/admin/"):] or "index.html")
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        path = path[len("/admin"):]

        # Every state-changing call must carry a header browsers cannot add
        # cross-site without a CORS preflight (which is never granted).
        if method != "GET" and req.headers.get("x-spider-admin") != "1":
            return self._json(HTTPStatus.FORBIDDEN, {"error": "missing request header"})

        token = req.cookie(COOKIE)
        user = self.auth.session_user(token)

        if path == "/api/session" and method == "GET":
            return self._json(HTTPStatus.OK, {"user": user, "accounts": self.auth.accounts_state(),
                                              "users_file": self.auth.owrx_users_file,
                                              "version": __version__})
        if path == "/api/login" and method == "POST":
            data = req.json() or {}
            wait = self.auth.locked_out(req.client)
            if wait:
                return self._json(HTTPStatus.TOO_MANY_REQUESTS,
                                  {"error": "Too many failed attempts, try again in %d s" % wait})
            token = self.auth.login(req.client, str(data.get("user", "")), str(data.get("password", "")))
            if not token:
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "Wrong user name or password"})
            return self._json(HTTPStatus.OK, {"ok": True},
                              {"Set-Cookie": self._session_cookie(token, 12 * 3600)})
        if path == "/api/logout" and method == "POST":
            self.auth.logout(token)
            return self._json(HTTPStatus.OK, {"ok": True}, {"Set-Cookie": self._session_cookie("", 0)})

        if not user:
            return self._json(HTTPStatus.UNAUTHORIZED, {"error": "login required"})

        if path == "/api/config" and method == "GET":
            return self._json(HTTPStatus.OK, self.config.redacted())
        if path == "/api/config" and method == "POST":
            data = req.json()
            if not isinstance(data, dict):
                return self._json(HTTPStatus.BAD_REQUEST, {"errors": ["invalid JSON"]})
            source_changed, errors = self.config.update(data)
            if errors:
                return self._json(HTTPStatus.BAD_REQUEST, {"errors": errors})
            self.config.save()
            log.info("configuration changed by %s", user)
            if source_changed:
                self.recent.clear()
                await self.source.restart(self.config.data)
            await self._broadcast({"type": "config", "config": self.config.public()})
            if source_changed:
                await self._broadcast({"type": "spots", "spots": [], "reset": True})
            return self._json(HTTPStatus.OK, self.config.redacted())
        if path == "/api/status" and method == "GET":
            return self._json(HTTPStatus.OK, {
                "version": __version__,
                "uptime": int(time.time() - self.started),
                "source": self.config["source"],
                "connection": self.source.status.as_dict(),
                "browsers": len(self.clients),
                "recent": list(self.recent)[-25:][::-1],
                "log": list(self.log_buffer.lines)[-60:][::-1],
            })
        return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _static(self, name: str) -> Tuple[HTTPStatus, Dict[str, str], bytes]:
        if name not in ADMIN_FILES:
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        with open(os.path.join(ADMIN_DIR, name), "rb") as fh:
            body = fh.read()
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        return HTTPStatus.OK, {"Content-Type": ctype, "Cache-Control": "no-cache"}, body
