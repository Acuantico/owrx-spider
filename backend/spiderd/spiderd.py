#!/usr/bin/env python3
"""
spiderd: DX Cluster (DXSpider / CC-Cluster) telnet client to WebSocket bridge.

Asyncio is used to run the telnet client and the WebSocket server concurrently
in a single event loop, which keeps the service lightweight and easy to stop.
"""

import argparse
import asyncio
import configparser
import contextlib
import json
import logging
import re
import signal
import time
from typing import Dict, Optional

from websockets.legacy.server import serve

DX_RE = re.compile(r"^DX\s+de\s+(\S+):\s*([0-9.]+)\s+(\S+)\s+(.*)$", re.IGNORECASE)

MODE_TOKENS = {
    "CW",
    "SSB",
    "USB",
    "LSB",
    "AM",
    "FM",
    "FT8",
    "FT4",
    "RTTY",
    "PSK",
    "DIGI",
    "JT65",
    "JT9",
}

BANDS = [
    ("160m", 1800000, 2000000),
    ("80m", 3500000, 4000000),
    ("60m", 5300000, 5400000),
    ("40m", 7000000, 7300000),
    ("30m", 10100000, 10150000),
    ("20m", 14000000, 14350000),
    ("17m", 18068000, 18168000),
    ("15m", 21000000, 21450000),
    ("12m", 24890000, 24990000),
    ("10m", 28000000, 29700000),
    ("6m", 50000000, 54000000),
    ("4m", 70000000, 70500000),
    ("2m", 144000000, 148000000),
]


def parse_frequency(value: str) -> Optional[int]:
    try:
        freq = float(value)
    except ValueError:
        return None

    if freq <= 0:
        return None

    # Most clusters report kHz (e.g. 14074.0). Assume kHz under 1 MHz.
    if freq < 1_000_000:
        return int(freq * 1000)

    return int(freq)


def band_for_freq(freq_hz: int) -> str:
    for name, start, end in BANDS:
        if start <= freq_hz <= end:
            return name
    return ""


def extract_mode_and_comment(rest: str) -> (str, str):
    rest = rest.strip()
    if not rest:
        return "", ""

    parts = rest.split()
    if parts and parts[0].upper() in MODE_TOKENS:
        mode = parts[0].upper()
        comment = " ".join(parts[1:]).strip()
        return mode, comment

    # Try to detect a mode anywhere in the comment.
    for token in parts:
        t = token.upper()
        if t in MODE_TOKENS:
            return t, rest

    return "", rest


def sanitize_telnet(data: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == 255:  # IAC
            i += 1
            if i < len(data) and data[i] in (251, 252, 253, 254):
                i += 2
            else:
                i += 1
            continue
        if b in (10, 13) or b >= 32:
            out.append(b)
        i += 1
    return out.decode("utf-8", errors="ignore")


class SpiderD:
    def __init__(self, cfg: configparser.ConfigParser) -> None:
        self.cfg = cfg
        self.ws_clients = set()
        self.stop_event = asyncio.Event()
        self.cluster_task = None
        self.ws_server = None

        self.cluster_host = cfg.get("cluster", "host", fallback="localhost")
        self.cluster_port = cfg.getint("cluster", "port", fallback=7300)
        self.cluster_user = cfg.get("cluster", "user", fallback="")
        self.cluster_password = cfg.get("cluster", "password", fallback="")

        self.bind_host = cfg.get("server", "bind", fallback="127.0.0.1")
        self.bind_port = cfg.getint("server", "port", fallback=7373)
        self.ws_path = cfg.get("server", "path", fallback="/spots")

        self.reconnect_initial = cfg.getfloat("reconnect", "initial_delay", fallback=3.0)
        self.reconnect_max = cfg.getfloat("reconnect", "max_delay", fallback=60.0)
        self.read_timeout = cfg.getfloat("cluster", "read_timeout", fallback=120.0)

    async def start(self) -> None:
        self.ws_server = await serve(
            self.handle_ws,
            self.bind_host,
            self.bind_port,
            ping_interval=30,
            ping_timeout=30,
            max_size=1_000_000,
        )
        logging.info("WebSocket server listening on ws://%s:%s%s", self.bind_host, self.bind_port, self.ws_path)

        self.cluster_task = asyncio.create_task(self.cluster_loop())
        await self.stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        logging.info("Shutting down")

        if self.cluster_task:
            self.cluster_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.cluster_task

        if self.ws_server:
            self.ws_server.close()
            await self.ws_server.wait_closed()

        for ws in list(self.ws_clients):
            with contextlib.suppress(Exception):
                await ws.close()

    async def handle_ws(self, websocket, path) -> None:
        if path != self.ws_path:
            await websocket.close()
            return

        self.ws_clients.add(websocket)
        logging.info("WebSocket client connected (%d total)", len(self.ws_clients))
        try:
            await websocket.wait_closed()
        finally:
            self.ws_clients.discard(websocket)
            logging.info("WebSocket client disconnected (%d total)", len(self.ws_clients))

    async def broadcast(self, payload: Dict) -> None:
        if not self.ws_clients:
            return

        message = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        stale = []
        for ws in self.ws_clients:
            try:
                await asyncio.wait_for(ws.send(message), timeout=1.5)
            except Exception:
                stale.append(ws)

        for ws in stale:
            self.ws_clients.discard(ws)

    async def cluster_loop(self) -> None:
        delay = self.reconnect_initial
        while not self.stop_event.is_set():
            try:
                await self.run_cluster_once()
                delay = self.reconnect_initial
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.warning("Cluster connection error: %s", exc)
                await asyncio.sleep(delay)
                delay = min(self.reconnect_max, delay * 1.5)

    async def run_cluster_once(self) -> None:
        logging.info("Connecting to cluster %s:%d", self.cluster_host, self.cluster_port)
        reader, writer = await asyncio.open_connection(self.cluster_host, self.cluster_port)

        login_sent = False
        password_sent = False

        async def send_line(line: str) -> None:
            writer.write((line + "\n").encode("utf-8"))
            await writer.drain()

        async def delayed_login() -> None:
            nonlocal login_sent
            await asyncio.sleep(2.0)
            if self.cluster_user and not login_sent:
                await send_line(self.cluster_user)
                login_sent = True

        login_task = asyncio.create_task(delayed_login())

        try:
            while not self.stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(reader.readline(), timeout=self.read_timeout)
                except asyncio.TimeoutError:
                    logging.info("Cluster read timeout, reconnecting")
                    break

                if not raw:
                    logging.info("Cluster connection closed")
                    break

                line = sanitize_telnet(raw).strip()
                if not line:
                    continue

                lower = line.lower()
                if self.cluster_user and not login_sent and ("login" in lower or "call" in lower):
                    await send_line(self.cluster_user)
                    login_sent = True
                    continue

                if self.cluster_password and not password_sent and "password" in lower:
                    await send_line(self.cluster_password)
                    password_sent = True
                    continue

                spot = self.parse_spot(line)
                if spot:
                    await self.broadcast(spot)

        finally:
            login_task.cancel()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def parse_spot(self, line: str) -> Optional[Dict]:
        match = DX_RE.match(line)
        if not match:
            return None

        spotter = match.group(1)
        freq_raw = match.group(2)
        call = match.group(3)
        rest = match.group(4)

        freq_hz = parse_frequency(freq_raw)
        if freq_hz is None:
            return None

        mode, comment = extract_mode_and_comment(rest)

        payload = {
            "freq": int(freq_hz),
            "call": call.upper(),
            "mode": mode or "UNKNOWN",
            "comment": comment,
            "spotter": spotter.upper(),
            "band": band_for_freq(freq_hz),
            "time": int(time.time()),
        }

        return payload


def load_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(path)
    return cfg


def setup_logging(cfg: configparser.ConfigParser) -> None:
    level_name = cfg.get("logging", "level", fallback="INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


async def main_async(args) -> None:
    cfg = load_config(args.config)
    setup_logging(cfg)

    service = SpiderD(cfg)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, service.stop_event.set)
        except NotImplementedError:
            pass

    await service.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="DX Cluster to WebSocket bridge")
    parser.add_argument("--config", default="spiderd.conf", help="Path to spiderd.conf")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
