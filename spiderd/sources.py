"""Cluster connections: telnet DX cluster or MQTT broker, with reconnection."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from .mqtt import MqttClient
from .spots import parse_dx_line, parse_mqtt_payload

log = logging.getLogger("spiderd.source")

SpotHandler = Callable[[Dict[str, Any]], Awaitable[None]]

LOGIN_PROMPT = re.compile(r"(login|call(sign)?)\s*[:>]?\s*$|enter your call", re.IGNORECASE)
PASSWORD_PROMPT = re.compile(r"password\s*[:>]?\s*$", re.IGNORECASE)
LOGIN_FAILED = re.compile(r"(invalid|bad|wrong|incorrect) (call|login|password)|access denied|not allowed",
                          re.IGNORECASE)

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


def strip_telnet(data: bytes, reply: bytearray) -> bytes:
    """Remove telnet negotiation from ``data``; refuse every option in ``reply``."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b != IAC:
            out.append(b)
            i += 1
            continue
        if i + 1 >= n:
            break
        cmd = data[i + 1]
        if cmd in (DO, DONT, WILL, WONT) and i + 2 < n:
            opt = data[i + 2]
            if cmd == DO:
                reply += bytes([IAC, WONT, opt])
            elif cmd == WILL:
                reply += bytes([IAC, DONT, opt])
            i += 3
        elif cmd == SB:
            end = data.find(bytes([IAC, SE]), i)
            i = n if end < 0 else end + 2
        elif cmd == IAC:
            out.append(IAC)
            i += 2
        else:
            i += 2
    return bytes(out)


class Status:
    def __init__(self) -> None:
        self.state = "disabled"  # disabled | connecting | connected | error
        self.detail = ""
        self.since = time.time()
        self.spots = 0
        self.last_spot = 0.0

    def set(self, state: str, detail: str = "") -> None:
        if state != self.state or detail != self.detail:
            self.since = time.time()
        self.state = state
        self.detail = detail

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "detail": self.detail,
            "since": int(self.since),
            "spots": self.spots,
            "last_spot": int(self.last_spot),
        }


async def telnet_session(cfg: Dict[str, Any], status: Status, on_spot: SpotHandler,
                         idle_timeout: float = 300.0) -> None:
    host, port = cfg["host"], int(cfg["port"])
    callsign, password = cfg["callsign"], cfg["password"]
    status.set("connecting", "%s:%d" % (host, port))
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 20)
    log.info("telnet connected to %s:%d", host, port)

    async def send(line: str) -> None:
        writer.write(line.encode("utf-8") + b"\r\n")
        await writer.drain()

    login_sent = False
    password_sent = False
    connected_at = time.monotonic()
    pending = ""
    try:
        while True:
            # A cluster that never shows a recognizable prompt still gets
            # the callsign after a few seconds.
            timeout = 4.0 if not login_sent else idle_timeout
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout)
            except asyncio.TimeoutError:
                if not login_sent:
                    await send(callsign)
                    login_sent = True
                    continue
                raise ConnectionError("no data from cluster for %d s" % idle_timeout)
            if not chunk:
                raise ConnectionError("cluster closed the connection")
            reply = bytearray()
            text = strip_telnet(chunk, reply).decode("utf-8", errors="replace")
            if reply:
                writer.write(bytes(reply))
            pending += text.replace("\r", "")
            *lines, pending = pending.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if LOGIN_FAILED.search(line) and time.monotonic() - connected_at < 60:
                    raise PermissionError("login refused: %s" % line[:120])
                spot = parse_dx_line(line)
                if spot:
                    if status.state != "connected":
                        status.set("connected", "%s:%d as %s" % (host, port, callsign))
                    await on_spot(spot)
                elif not login_sent and LOGIN_PROMPT.search(line):
                    await send(callsign)
                    login_sent = True
                elif password and not password_sent and PASSWORD_PROMPT.search(line):
                    await send(password)
                    password_sent = True
            # Prompts usually come without a trailing newline.
            prompt = pending.strip()
            if prompt and not login_sent and LOGIN_PROMPT.search(prompt):
                await send(callsign)
                login_sent = True
                pending = ""
            elif prompt and password and not password_sent and PASSWORD_PROMPT.search(prompt):
                await send(password)
                password_sent = True
                pending = ""
            elif login_sent and status.state != "connected" and time.monotonic() - connected_at > 2:
                status.set("connected", "%s:%d as %s" % (host, port, callsign))
            if len(pending) > 8192:
                pending = ""
    finally:
        writer.close()


async def mqtt_session(cfg: Dict[str, Any], status: Status, on_spot: SpotHandler) -> None:
    status.set("connecting", cfg["url"])
    client = MqttClient(
        cfg["url"],
        cfg["topics"],
        username=cfg["username"],
        password=cfg["password"],
        client_id=cfg["client_id"],
        qos=cfg["qos"],
    )

    async def on_message(topic: str, payload: bytes) -> None:
        for spot in parse_mqtt_payload(topic, payload):
            await on_spot(spot)

    def on_connected() -> None:
        log.info("MQTT connected to %s, topics: %s", cfg["url"], ", ".join(cfg["topics"]))
        status.set("connected", "%s (%d topics)" % (cfg["url"], len(cfg["topics"])))

    await client.run(on_message, on_connected)
    raise ConnectionError("MQTT session ended")


class SourceRunner:
    """Keeps exactly one cluster connection alive according to the config."""

    def __init__(self, on_spot: SpotHandler, initial_delay: float = 3.0, max_delay: float = 60.0) -> None:
        self.on_spot = on_spot
        self.status = Status()
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self._task: Optional[asyncio.Task] = None

    async def _counted(self, spot: Dict[str, Any]) -> None:
        self.status.spots += 1
        self.status.last_spot = time.time()
        await self.on_spot(spot)

    async def restart(self, config: Dict[str, Any]) -> None:
        await self.stop()
        if not config["enabled"]:
            self.status.set("disabled", "")
            return
        self._task = asyncio.ensure_future(self._loop(config))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self, config: Dict[str, Any]) -> None:
        delay = self.initial_delay
        kind = config["source"]
        while True:
            started = time.monotonic()
            try:
                if kind == "telnet":
                    await telnet_session(config["telnet"], self.status, self._counted)
                else:
                    await mqtt_session(config["mqtt"], self.status, self._counted)
            except asyncio.CancelledError:
                raise
            except PermissionError as exc:
                # Wrong credentials will not fix themselves quickly.
                self.status.set("error", str(exc))
                log.warning("%s source: %s", kind, exc)
                delay = self.max_delay
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                self.status.set("error", message)
                log.warning("%s source: %s", kind, message)
            if time.monotonic() - started > 60:
                delay = self.initial_delay  # it was working for a while
            log.info("reconnecting in %.0f s", delay)
            await asyncio.sleep(delay)
            delay = min(self.max_delay, delay * 2)
