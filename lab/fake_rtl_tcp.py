#!/usr/bin/env python3
"""Small read-only rtl_tcp-compatible IQ source for the isolated OWRX lab."""

import math
import socket
import socketserver
import struct
import threading
import time


HOST = "0.0.0.0"
PORT = 1234
SAMPLE_RATE = 250_000
BLOCK_SAMPLES = 4096


def make_iq_block():
    data = bytearray(BLOCK_SAMPLES * 2)
    for sample in range(BLOCK_SAMPLES):
        # Two deterministic tones give the clean OpenWebRX+ installation
        # something visible without requiring access to an actual SDR.
        phase_a = 2.0 * math.pi * 18_000 * sample / SAMPLE_RATE
        phase_b = 2.0 * math.pi * -42_000 * sample / SAMPLE_RATE
        i_value = 127 + 34 * math.cos(phase_a) + 18 * math.cos(phase_b)
        q_value = 127 + 34 * math.sin(phase_a) + 18 * math.sin(phase_b)
        data[sample * 2] = max(0, min(255, round(i_value)))
        data[sample * 2 + 1] = max(0, min(255, round(q_value)))
    return bytes(data)


IQ_BLOCK = make_iq_block()


class RtlTcpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # rtl_tcp header: magic, tuner type R820T, gain count.
        self.request.sendall(b"RTL0" + struct.pack(">II", 5, 0))

        def drain_commands():
            try:
                while self.request.recv(5):
                    pass
            except OSError:
                pass

        threading.Thread(target=drain_commands, daemon=True).start()
        block_duration = BLOCK_SAMPLES / SAMPLE_RATE
        try:
            while True:
                started = time.monotonic()
                self.request.sendall(IQ_BLOCK)
                remaining = block_duration - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class RtlTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"Fake rtl_tcp listening on {HOST}:{PORT} at {SAMPLE_RATE} S/s", flush=True)
    with RtlTcpServer((HOST, PORT), RtlTcpHandler) as server:
        server.serve_forever()
