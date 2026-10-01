"""Minimal RFC 6455 WebSocket implementation on top of asyncio streams.

Only what spiderd needs: the server side for the browser spot stream and
the client side for MQTT over WebSockets. No extensions, no compression.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import ssl
import struct
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

MAX_MESSAGE = 4 * 1024 * 1024


class WebSocketError(Exception):
    pass


class ConnectionClosed(WebSocketError):
    pass


def accept_key(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _mask(data: bytes, key: bytes) -> bytes:
    if not data:
        return data
    # XOR in one go using integers; fast enough for spot-sized payloads.
    repeated = (key * (len(data) // 4 + 1))[: len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(repeated, "big")).to_bytes(len(data), "big")


def encode_frame(opcode: int, payload: bytes, mask: bool) -> bytes:
    header = bytearray([0x80 | opcode])
    length = len(payload)
    mask_bit = 0x80 if mask else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length < 1 << 16:
        header.append(mask_bit | 126)
        header += struct.pack("!H", length)
    else:
        header.append(mask_bit | 127)
        header += struct.pack("!Q", length)
    if mask:
        key = os.urandom(4)
        return bytes(header) + key + _mask(payload, key)
    return bytes(header) + payload


class WebSocket:
    """A connected WebSocket, either side."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, client: bool,
                 subprotocol: str = "") -> None:
        self.reader = reader
        self.writer = writer
        self.client = client
        self.subprotocol = subprotocol
        self.closed = False
        self._send_lock = asyncio.Lock()

    @property
    def peer(self) -> str:
        peer = self.writer.get_extra_info("peername")
        return "%s:%s" % (peer[0], peer[1]) if peer else "?"

    async def _send(self, opcode: int, payload: bytes) -> None:
        if self.closed:
            raise ConnectionClosed("closed")
        frame = encode_frame(opcode, payload, mask=self.client)
        async with self._send_lock:
            self.writer.write(frame)
            await self.writer.drain()

    async def send_text(self, text: str) -> None:
        await self._send(OP_TEXT, text.encode("utf-8"))

    async def send_binary(self, data: bytes) -> None:
        await self._send(OP_BINARY, data)

    async def ping(self, data: bytes = b"") -> None:
        await self._send(OP_PING, data)

    async def _read_frame(self) -> Tuple[bool, int, bytes]:
        try:
            head = await self.reader.readexactly(2)
            fin = bool(head[0] & 0x80)
            opcode = head[0] & 0x0F
            masked = bool(head[1] & 0x80)
            length = head[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", await self.reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", await self.reader.readexactly(8))[0]
            if length > MAX_MESSAGE:
                raise WebSocketError("frame too large")
            key = await self.reader.readexactly(4) if masked else b""
            payload = await self.reader.readexactly(length) if length else b""
        except (asyncio.IncompleteReadError, ConnectionError) as exc:
            self.closed = True
            raise ConnectionClosed("connection lost") from exc
        if masked:
            payload = _mask(payload, key)
        return fin, opcode, payload

    async def recv(self) -> Tuple[int, bytes]:
        """Return (opcode, payload) of the next data message.

        Control frames are handled here: pings are answered and a close
        frame raises :class:`ConnectionClosed`.
        """
        buffer = bytearray()
        message_opcode = None
        while True:
            fin, opcode, payload = await self._read_frame()
            if opcode == OP_PING:
                try:
                    await self._send(OP_PONG, payload)
                except (ConnectionError, ConnectionClosed):
                    pass
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                await self.close()
                raise ConnectionClosed("closed by peer")
            if opcode in (OP_TEXT, OP_BINARY):
                message_opcode = opcode
                buffer = bytearray(payload)
            elif opcode == OP_CONT and message_opcode is not None:
                buffer += payload
                if len(buffer) > MAX_MESSAGE:
                    raise WebSocketError("message too large")
            else:
                raise WebSocketError("unexpected opcode %d" % opcode)
            if fin:
                return message_opcode, bytes(buffer)

    async def close(self, code: int = 1000) -> None:
        if self.closed:
            return
        try:
            await self._send(OP_CLOSE, struct.pack("!H", code))
        except Exception:
            pass
        self.closed = True
        try:
            self.writer.close()
        except Exception:
            pass


async def server_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                           headers: Dict[str, str]) -> WebSocket:
    """Complete the upgrade for an already parsed HTTP request."""
    key = headers.get("sec-websocket-key", "")
    if headers.get("upgrade", "").lower() != "websocket" or not key:
        raise WebSocketError("not a websocket upgrade")
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Accept: %s\r\n\r\n" % accept_key(key)
    )
    writer.write(response.encode("ascii"))
    await writer.drain()
    return WebSocket(reader, writer, client=False)


async def connect(url: str, *, subprotocol: str = "", timeout: float = 15.0,
                  extra_headers: Optional[Dict[str, str]] = None) -> WebSocket:
    """Open a client WebSocket to ``ws://`` or ``wss://`` ``url``."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("ws", "wss"):
        raise WebSocketError("unsupported scheme %r" % scheme)
    host = parts.hostname or ""
    port = parts.port or (443 if scheme == "wss" else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    ssl_ctx = ssl.create_default_context() if scheme == "wss" else None

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port, ssl=ssl_ctx, server_hostname=host if ssl_ctx else None),
        timeout,
    )
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    # Like browsers, leave the default port out of Host: some reverse proxies
    # (e.g. the URE broker) answer "Host: name:443" with a plain 200 page.
    default_port = 443 if scheme == "wss" else 80
    host_header = host if port == default_port else "%s:%d" % (host, port)
    lines = [
        "GET %s HTTP/1.1" % path,
        "Host: %s" % host_header,
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: %s" % key,
        "Sec-WebSocket-Version: 13",
    ]
    if subprotocol:
        lines.append("Sec-WebSocket-Protocol: %s" % subprotocol)
    for name, value in (extra_headers or {}).items():
        lines.append("%s: %s" % (name, value))
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
    await writer.drain()

    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
    except Exception as exc:
        writer.close()
        raise WebSocketError("no handshake response") from exc
    head = raw.decode("latin-1").split("\r\n")
    status = head[0].split(" ", 2)
    if len(status) < 2 or status[1] != "101":
        writer.close()
        raise WebSocketError("handshake rejected: %s" % head[0])
    headers = {}
    for line in head[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    if headers.get("sec-websocket-accept") != accept_key(key):
        writer.close()
        raise WebSocketError("bad Sec-WebSocket-Accept")
    return WebSocket(reader, writer, client=True, subprotocol=headers.get("sec-websocket-protocol", ""))
