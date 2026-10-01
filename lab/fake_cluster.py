#!/usr/bin/env python3
"""Fake DXSpider-like telnet node for the lab (port 7300).

Login prompt without newline, optional password for EA1PW (pw123), rejects
the callsign BAD, then streams "DX de" lines on 20 m.
"""

import asyncio
import random
import time

CALLS = ["K1ABC", "JA1XYZ", "VK2DEF", "ZS6GHI", "PY2JKL", "W5MNO", "9A1PQR", "OH2STU", "VE3VWX", "LU1YZA",
         "EA8BCD", "G4EFG", "DL1HIJ", "I2KLM", "SP3NOP"]
SPOTTERS = ["EA4URE", "EA5WU-#", "DK9IP-#", "EA1ABC", "F5XYZ"]


def make_line():
    kind = random.choice(["cw", "cw", "ft8", "ssb", "ssb-nomode", "rtty"])
    if kind == "cw":
        freq, comment = random.uniform(14010, 14065), "CW %d dB %d WPM CQ" % (random.randint(5, 35), random.randint(18, 30))
    elif kind == "ft8":
        freq, comment = 14074 + random.uniform(0.3, 2.8), "FT8 %+d dB" % random.randint(-20, 10)
    elif kind == "rtty":
        freq, comment = random.uniform(14080, 14095), "RTTY contest"
    elif kind == "ssb":
        freq, comment = random.uniform(14150, 14290), "USB 59 tnx QSO"
    else:
        freq, comment = random.uniform(14150, 14290), "up 5 listening"
    call = random.choice(CALLS)
    spotter = random.choice(SPOTTERS)
    head = "DX de %s:" % spotter
    return "%-15s %8.1f  %-12s %-30s %sZ" % (head, freq, call, comment[:30], time.strftime("%H%M", time.gmtime()))


async def handle(reader, writer):
    peer = writer.get_extra_info("peername")
    print("connection from", peer)
    try:
        writer.write(b"\xff\xfb\x01\xff\xfb\x03")  # IAC WILL ECHO, IAC WILL SGA
        writer.write(b"Welcome to LAB-CLUSTER (fake DXSpider)\r\n\r\nlogin: ")
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), 60)
        call = raw.replace(b"\xff", b"").decode(errors="ignore").strip().upper()
        call = "".join(ch for ch in call if ch.isalnum() or ch in "/-")
        print("login as", call)
        if call == "BAD" or not call:
            writer.write(b"Sorry, invalid callsign\r\n")
            await writer.drain()
            return
        if call == "EA1PW":
            writer.write(b"password: ")
            await writer.drain()
            pw = (await asyncio.wait_for(reader.readline(), 60)).decode(errors="ignore").strip()
            if pw != "pw123":
                writer.write(b"Sorry, wrong password\r\n")
                await writer.drain()
                return
        writer.write(("Hello %s, this is LAB-CLUSTER in Madrid\r\n%s de LAB-CLUSTER %s dxspider >\r\n"
                      % (call, call, time.strftime("%d-%b-%Y %H%MZ", time.gmtime()))).encode())
        await writer.drain()
        while True:
            await asyncio.sleep(random.uniform(0.8, 2.0))
            writer.write((make_line() + "\r\n").encode())
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        print("closed", peer)
        writer.close()


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", 7300)
    print("fake cluster on :7300")
    async with server:
        await server.serve_forever()


asyncio.run(main())
