#!/usr/bin/env python3
"""Publishes URE-style JSON spots to the lab broker (raw MQTT 3.1.1, no deps)."""

import json
import random
import socket
import struct
import time
from datetime import datetime, timezone

CALLS = ["EA6AAA", "CT1BBB", "OK1CCC", "HB9DDD", "UA3EEE", "YB0FFF", "KH6GGG", "ZL1HHH", "5B4III", "4X1JJJ"]


def s(text):
    data = text.encode()
    return struct.pack("!H", len(data)) + data


def rl(n):
    out = bytearray()
    while True:
        b, n = n % 128, n // 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def pkt(first, body):
    return bytes([first]) + rl(len(body)) + body


def connect():
    sock = socket.create_connection(("mosquitto", 1883), 10)
    body = s("MQTT") + bytes([4, 0x02 | 0x80 | 0x40]) + struct.pack("!H", 60)
    body += s("lab-publisher") + s("publisher") + s("publisher-pass")
    sock.sendall(pkt(0x10, body))
    ack = sock.recv(4)
    if len(ack) < 4 or ack[3] != 0:
        raise ConnectionError("CONNACK %r" % ack)
    return sock


def spot():
    kind = random.choice(["dx", "rbn-cw", "rbn-dig"])
    if kind == "rbn-cw":
        qrg, mode, cmt = random.uniform(14012, 14060), "CW", "CW %d dB 24 WPM CQ" % random.randint(5, 30)
    elif kind == "rbn-dig":
        qrg, mode, cmt = 14074 + random.uniform(0.2, 2.9), "DIG", "FT8 %+d dB" % random.randint(-20, 5)
    else:
        qrg, mode, cmt = random.uniform(14160, 14280), "", "big signal 59+"
    payload = {
        "isots": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "src": random.choice(["EA4URE", "EA3XYZ-#"]),
        "dx": random.choice(CALLS),
        "qrg": "%.1f" % qrg,
        "band": 20,
        "mode": mode,
        "cmt": cmt,
    }
    return "lab/spots/" + kind, json.dumps(payload)


while True:
    try:
        sock = connect()
        print("connected to broker")
        last_ping = time.time()
        while True:
            topic, payload = spot()
            sock.sendall(pkt(0x30, s(topic) + payload.encode()))
            if time.time() - last_ping > 30:
                sock.sendall(b"\xc0\x00")
                last_ping = time.time()
            time.sleep(random.uniform(0.7, 1.8))
    except Exception as exc:
        print("publisher error:", exc)
        time.sleep(3)
