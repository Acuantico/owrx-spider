"""Minimal MQTT 3.1.1 subscriber over TCP, TLS, WebSocket or secure WebSocket.

URL schemes: ``mqtt://`` (1883), ``mqtts://`` (8883), ``ws://`` (80) and
``wss://`` (443). Only the subscriber side is implemented.
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import struct
import time
from typing import Awaitable, Callable, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from . import websocket

log = logging.getLogger("spiderd.mqtt")

CONNECT = 1
CONNACK = 2
PUBLISH = 3
PUBACK = 4
PUBREC = 5
PUBREL = 6
PUBCOMP = 7
SUBSCRIBE = 8
SUBACK = 9
PINGREQ = 12
PINGRESP = 13
DISCONNECT = 14

CONNACK_ERRORS = {
    1: "unacceptable protocol version",
    2: "client identifier rejected",
    3: "server unavailable",
    4: "bad user name or password",
    5: "not authorized",
}

DEFAULT_PORTS = {"mqtt": 1883, "tcp": 1883, "mqtts": 8883, "ssl": 8883, "ws": 80, "wss": 443}


class MqttError(Exception):
    pass


def encode_string(text: str) -> bytes:
    data = text.encode("utf-8")
    return struct.pack("!H", len(data)) + data


def encode_remaining_length(length: int) -> bytes:
    out = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length:
            byte |= 0x80
        out.append(byte)
        if not length:
            return bytes(out)


def packet(ptype: int, flags: int, body: bytes) -> bytes:
    return bytes([(ptype << 4) | flags]) + encode_remaining_length(len(body)) + body


def connect_packet(client_id: str, keepalive: int, username: str = "", password: str = "") -> bytes:
    flags = 0x02  # clean session
    payload = encode_string(client_id)
    if username:
        flags |= 0x80
        payload += encode_string(username)
        if password:
            flags |= 0x40
            payload += encode_string(password)
    body = encode_string("MQTT") + bytes([4, flags]) + struct.pack("!H", keepalive) + payload
    return packet(CONNECT, 0, body)


def subscribe_packet(packet_id: int, topics: List[str], qos: int) -> bytes:
    body = struct.pack("!H", packet_id)
    for topic in topics:
        body += encode_string(topic) + bytes([qos])
    return packet(SUBSCRIBE, 0x02, body)


def parse_publish(flags: int, body: bytes) -> Tuple[str, int, Optional[int], bytes]:
    qos = (flags >> 1) & 0x03
    tlen = struct.unpack("!H", body[:2])[0]
    topic = body[2:2 + tlen].decode("utf-8", errors="replace")
    pos = 2 + tlen
    packet_id = None
    if qos:
        packet_id = struct.unpack("!H", body[pos:pos + 2])[0]
        pos += 2
    return topic, qos, packet_id, body[pos:]


class _StreamTransport:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    async def read(self, n: int) -> bytes:
        try:
            return await self.reader.readexactly(n)
        except asyncio.IncompleteReadError as exc:
            raise MqttError("connection closed by broker") from exc

    async def write(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def close(self) -> None:
        try:
            self.writer.close()
        except Exception:
            pass


class _WsTransport:
    def __init__(self, ws: websocket.WebSocket) -> None:
        self.ws = ws
        self.buffer = bytearray()

    async def read(self, n: int) -> bytes:
        while len(self.buffer) < n:
            try:
                _, data = await self.ws.recv()
            except websocket.ConnectionClosed as exc:
                raise MqttError("connection closed by broker") from exc
            self.buffer += data
        out = bytes(self.buffer[:n])
        del self.buffer[:n]
        return out

    async def write(self, data: bytes) -> None:
        await self.ws.send_binary(data)

    async def close(self) -> None:
        await self.ws.close()


MessageHandler = Callable[[str, bytes], Awaitable[None]]


class MqttClient:
    def __init__(self, url: str, topics: List[str], *, username: str = "", password: str = "",
                 client_id: str = "", qos: int = 0, keepalive: int = 30,
                 connect_timeout: float = 15.0) -> None:
        self.url = url
        self.topics = [t for t in topics if t]
        self.username = username
        self.password = password
        self.client_id = client_id or "owrx-spider-" + os.urandom(4).hex()
        self.qos = max(0, min(2, int(qos)))
        self.keepalive = max(10, int(keepalive))
        self.connect_timeout = connect_timeout
        self.transport = None
        self._last_rx = 0.0

    async def _open(self):
        parts = urlsplit(self.url)
        scheme = parts.scheme.lower()
        if scheme not in DEFAULT_PORTS:
            raise MqttError("unsupported URL scheme %r (use mqtt, mqtts, ws or wss)" % scheme)
        if parts.username and not self.username:
            self.username = unquote(parts.username)
            self.password = unquote(parts.password or "")
        host = parts.hostname
        if not host:
            raise MqttError("missing broker host")
        port = parts.port or DEFAULT_PORTS[scheme]
        if scheme in ("ws", "wss"):
            netloc = host if parts.port is None else "%s:%d" % (host, port)
            ws_url = "%s://%s%s" % (scheme, netloc, parts.path or "/mqtt")
            if parts.query:
                ws_url += "?" + parts.query
            ws = await websocket.connect(ws_url, subprotocol="mqtt", timeout=self.connect_timeout)
            return _WsTransport(ws)
        ssl_ctx = ssl.create_default_context() if scheme in ("mqtts", "ssl") else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_ctx, server_hostname=host if ssl_ctx else None),
            self.connect_timeout,
        )
        return _StreamTransport(reader, writer)

    async def _read_packet(self) -> Tuple[int, int, bytes]:
        first = (await self.transport.read(1))[0]
        multiplier = 1
        length = 0
        for _ in range(4):
            byte = (await self.transport.read(1))[0]
            length += (byte & 0x7F) * multiplier
            if not byte & 0x80:
                break
            multiplier *= 128
        else:
            raise MqttError("malformed remaining length")
        body = await self.transport.read(length) if length else b""
        self._last_rx = time.monotonic()
        return first >> 4, first & 0x0F, body

    async def run(self, on_message: MessageHandler, on_connected: Optional[Callable[[], None]] = None) -> None:
        """Connect, subscribe and dispatch messages until the connection fails."""
        self.transport = await self._open()
        pinger = None
        try:
            await self.transport.write(connect_packet(self.client_id, self.keepalive, self.username, self.password))
            ptype, _, body = await asyncio.wait_for(self._read_packet(), self.connect_timeout)
            if ptype != CONNACK or len(body) < 2:
                raise MqttError("unexpected reply to CONNECT")
            if body[1] in (4, 5):
                raise PermissionError("broker refused connection: %s" % CONNACK_ERRORS[body[1]])
            if body[1] != 0:
                raise MqttError("broker refused connection: %s" % CONNACK_ERRORS.get(body[1], "code %d" % body[1]))

            if not self.topics:
                raise MqttError("no topics configured")
            await self.transport.write(subscribe_packet(1, self.topics, self.qos))
            ptype, flags, body = await asyncio.wait_for(self._read_packet(), self.connect_timeout)
            while ptype == PUBLISH:  # retained messages may arrive before SUBACK
                await self._handle_publish(flags, body, on_message)
                ptype, flags, body = await asyncio.wait_for(self._read_packet(), self.connect_timeout)
            if ptype != SUBACK:
                raise MqttError("unexpected reply to SUBSCRIBE")
            refused = [t for t, code in zip(self.topics, body[2:]) if code == 0x80]
            if len(refused) == len(self.topics):
                raise MqttError("broker refused every subscription: %s" % ", ".join(refused))
            for topic in refused:
                log.warning("subscription refused by broker: %s", topic)
            if on_connected:
                on_connected()

            pinger = asyncio.ensure_future(self._ping_loop())
            while True:
                read = asyncio.ensure_future(self._read_packet())
                done, _pending = await asyncio.wait({read, pinger}, return_when=asyncio.FIRST_COMPLETED)
                if pinger in done:
                    read.cancel()
                    pinger.result()  # re-raises the keepalive failure
                ptype, flags, body = read.result()
                if ptype == PUBLISH:
                    await self._handle_publish(flags, body, on_message)
                elif ptype == PUBREL:
                    await self.transport.write(packet(PUBCOMP, 0, body[:2]))
        finally:
            if pinger:
                pinger.cancel()
            try:
                await asyncio.wait_for(self.transport.write(packet(DISCONNECT, 0, b"")), 2)
            except Exception:
                pass
            await self.transport.close()

    async def _handle_publish(self, flags: int, body: bytes, on_message: MessageHandler) -> None:
        topic, qos, packet_id, payload = parse_publish(flags, body)
        if qos == 1:
            await self.transport.write(packet(PUBACK, 0, struct.pack("!H", packet_id)))
        elif qos == 2:
            await self.transport.write(packet(PUBREC, 0, struct.pack("!H", packet_id)))
        try:
            await on_message(topic, payload)
        except Exception:
            log.exception("error handling message on %s", topic)

    async def _ping_loop(self) -> None:
        interval = self.keepalive * 0.75
        while True:
            await asyncio.sleep(interval)
            if time.monotonic() - self._last_rx > self.keepalive * 1.5:
                raise MqttError("broker stopped answering (keepalive timeout)")
            await self.transport.write(packet(PINGREQ, 0, b""))
