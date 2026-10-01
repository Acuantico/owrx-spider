"""spiderd tests: python3 -m unittest discover -s tests (standard library only)."""

import asyncio
import hashlib
import json
import os
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spiderd import auth, mqtt, sources, spots, websocket  # noqa: E402
from spiderd.config import SECRET_PLACEHOLDER, Config  # noqa: E402
from spiderd.server import LogBuffer, SpiderServer  # noqa: E402


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


class SpotParsing(unittest.TestCase):
    def test_dxspider_line(self):
        s = spots.parse_dx_line("DX de EA5WU-#:   14025.0  K1ABC        CW 12 dB 25 WPM CQ             1234Z")
        self.assertEqual((s["freq"], s["call"], s["mode"], s["group"], s["spotter"], s["band"]),
                         (14025000, "K1ABC", "CW", "CW", "EA5WU-#", "20m"))
        self.assertEqual(s["comment"], "CW 12 dB 25 WPM CQ")

    def test_line_with_locator_and_no_mode(self):
        s = spots.parse_dx_line("DX de EA4URE:     7155.0  EA8XYZ       tnx qso      0930Z IL18")
        self.assertEqual((s["mode"], s["group"], s["comment"]), ("", "PHONE", "tnx qso"))

    def test_group_from_band_plan(self):
        self.assertEqual(spots.parse_dx_line("DX de X1AA: 14074.5 JA1AA  -10 dB 1200Z")["group"], "DIGITAL")
        self.assertEqual(spots.parse_dx_line("DX de X1AA: 7012.0 JA1AA  599 1200Z")["group"], "CW")

    def test_not_a_spot(self):
        self.assertIsNone(spots.parse_dx_line("EA4LAB de LAB-CLUSTER 1-Oct-2026 1400Z dxspider >"))
        self.assertIsNone(spots.parse_dx_line("WWV de VE7CC <18>:   SFI=150, A=5, K=1"))

    def test_ure_payload(self):
        payload = json.dumps({"isots": "2026-10-01T13:53:29", "src": "N6TV-#", "dx": "hl2oii", "qrg": "7074.0",
                              "band": 40, "mode": "DIG", "submode": "FTX", "cmt": "FT8  0dB Q:1"}).encode()
        (s,) = spots.parse_mqtt_payload("spider/spots/rbn-dig", payload)
        self.assertEqual((s["freq"], s["call"], s["mode"], s["group"], s["band"]), (7074000, "HL2OII", "FT8", "DIGITAL", "40m"))
        self.assertEqual(s["time"], 1790862809)

    def test_payload_shapes_and_units(self):
        msgs = [
            {"data": {"frequency": 14.2, "call": "AA1A"}},
            {"spot": {"frequencyHz": 14200000, "callsign": "AA1A"}},
            [{"freq": 14200, "dx": "AA1A"}, {"freq": 14201, "dx": "BB1B"}],
        ]
        for msg in msgs:
            out = spots.parse_mqtt_payload("t", json.dumps(msg).encode())
            self.assertEqual(out[0]["freq"], 14200000)
        self.assertEqual(len(spots.parse_mqtt_payload("t", json.dumps(msgs[2]).encode())), 2)

    def test_scaled_frequency_rescue(self):
        (s,) = spots.parse_mqtt_payload("t", b'{"qrg": 140740, "dx": "AA1A", "band": "20m"}')
        self.assertEqual(s["freq"], 14074000)
        (s,) = spots.parse_mqtt_payload("t", b'{"qrg": 1407400000, "dx": "AA1A"}')
        self.assertEqual(s["freq"], 14074000)

    def test_mode_from_topic_and_ms_timestamp(self):
        (s,) = spots.parse_mqtt_payload("x/rbn-cw", b'{"qrg": "21011.0", "dx": "AA1A", "ts": 1790862809000}')
        self.assertEqual((s["mode"], s["time"]), ("CW", 1790862809))

    def test_garbage(self):
        self.assertEqual(spots.parse_mqtt_payload("t", b"not json"), [])
        self.assertEqual(spots.parse_mqtt_payload("t", b'{"qrg": "x", "dx": "A"}'), [])
        self.assertEqual(spots.parse_mqtt_payload("t", b"[1, 2]"), [])

    def test_plain_dx_line_over_mqtt(self):
        (s,) = spots.parse_mqtt_payload("t", b"DX de EA1A: 14025.0 K1ABC CW 1200Z")
        self.assertEqual((s["call"], s["source"]), ("K1ABC", "mqtt"))


class Telnet(unittest.TestCase):
    def test_strip_negotiation(self):
        reply = bytearray()
        out = sources.strip_telnet(b"\xff\xfb\x01hello\xff\xfd\x18 world", reply)
        self.assertEqual(out, b"hello world")
        self.assertEqual(bytes(reply), b"\xff\xfe\x01\xff\xfc\x18")

    def _node(self, script):
        async def handle(reader, writer):
            await script(reader, writer)
            writer.close()
        return asyncio.start_server(handle, "127.0.0.1", 0)

    def test_login_prompt_without_newline_and_password(self):
        got = []

        async def script(reader, writer):
            writer.write(b"\xff\xfb\x01Welcome\r\nlogin: ")
            await writer.drain()
            line = await reader.readline()  # preceded by our IAC DONT reply
            assert bytes(b for b in line if 32 < b < 127) == b"EA1PW"
            writer.write(b"password: ")
            await writer.drain()
            assert (await reader.readline()).strip() == b"secret"
            writer.write(b"Hello EA1PW\r\nDX de EA4URE:  14025.0  K1ABC  CW 599  1200Z\r\n")
            await writer.drain()
            await asyncio.sleep(0.2)

        async def main():
            server = await self._node(script)
            port = server.sockets[0].getsockname()[1]
            status = sources.Status()

            async def on_spot(s):
                got.append(s)
            with self.assertRaises(ConnectionError):
                await sources.telnet_session({"host": "127.0.0.1", "port": port, "callsign": "EA1PW",
                                              "password": "secret"}, status, on_spot)
            server.close()
            return status
        status = run(main())
        self.assertEqual([s["call"] for s in got], ["K1ABC"])
        self.assertEqual(status.state, "connected")

    def test_login_refused(self):
        async def script(reader, writer):
            writer.write(b"login: ")
            await writer.drain()
            await reader.readline()
            writer.write(b"Sorry, invalid callsign\r\n")
            await writer.drain()
            await asyncio.sleep(0.2)

        async def main():
            server = await self._node(script)
            port = server.sockets[0].getsockname()[1]

            async def on_spot(s):
                pass
            with self.assertRaises(PermissionError):
                await sources.telnet_session({"host": "127.0.0.1", "port": port, "callsign": "BAD",
                                              "password": ""}, sources.Status(), on_spot)
            server.close()
        run(main())


class FakeBroker:
    """Tiny MQTT 3.1.1 broker: one subscriber, publishes test messages."""

    def __init__(self, messages, qos=0, password="pw"):
        self.messages = messages
        self.qos = qos
        self.password = password
        self.pubacks = []

    async def handle_stream(self, read, write):
        first, body = await self._packet(read)
        assert first >> 4 == mqtt.CONNECT
        flags = body[7]
        pos = 10
        n = struct.unpack("!H", body[pos:pos + 2])[0]
        pos += 2 + n
        user = pw = ""
        if flags & 0x80:
            n = struct.unpack("!H", body[pos:pos + 2])[0]
            user = body[pos + 2:pos + 2 + n].decode()
            pos += 2 + n
        if flags & 0x40:
            n = struct.unpack("!H", body[pos:pos + 2])[0]
            pw = body[pos + 2:pos + 2 + n].decode()
        if (user, pw) != ("u", self.password):
            await write(b"\x20\x02\x00\x04")
            return
        await write(b"\x20\x02\x00\x00")
        first, body = await self._packet(read)
        assert first >> 4 == mqtt.SUBSCRIBE
        await write(mqtt.packet(mqtt.SUBACK, 0, body[:2] + bytes([self.qos])))
        for i, (topic, payload) in enumerate(self.messages, start=1):
            pid = struct.pack("!H", i) if self.qos else b""
            await write(mqtt.packet(mqtt.PUBLISH, self.qos << 1, mqtt.encode_string(topic) + pid + payload))
            if self.qos == 1:
                first, body = await self._packet(read)
                self.pubacks.append(struct.unpack("!H", body)[0])
        await asyncio.sleep(0.3)

    async def _packet(self, read):
        first = (await read(1))[0]
        length, mult = 0, 1
        while True:
            b = (await read(1))[0]
            length += (b & 0x7F) * mult
            mult *= 128
            if not b & 0x80:
                break
        return first, (await read(length)) if length else b""


class Mqtt(unittest.TestCase):
    MESSAGES = [("spots/dx", b'{"qrg": "14025.0", "dx": "K1ABC"}'),
                ("spots/dx", b'{"qrg": "7074.5", "dx": "JA1XYZ", "mode": "FT8"}')]

    def _tcp(self, broker):
        async def handle(reader, writer):
            async def write(data):
                writer.write(data)
                await writer.drain()
            await broker.handle_stream(reader.readexactly, write)
            writer.close()
        return asyncio.start_server(handle, "127.0.0.1", 0)

    def _receive(self, url_fmt, broker, start_server, password="pw"):
        got = []

        async def main():
            server = await start_server(broker)
            port = server.sockets[0].getsockname()[1]
            client = mqtt.MqttClient(url_fmt % port, ["spots/#"], username="u", password=password, qos=broker.qos)

            async def on_message(topic, payload):
                got.extend(spots.parse_mqtt_payload(topic, payload))
            try:
                await client.run(on_message)
            finally:
                server.close()
        return got, main

    def test_tcp_qos0(self):
        got, main = self._receive("mqtt://127.0.0.1:%d", FakeBroker(self.MESSAGES), self._tcp)
        with self.assertRaises(mqtt.MqttError):
            run(main())
        self.assertEqual([s["call"] for s in got], ["K1ABC", "JA1XYZ"])

    def test_qos1_acknowledged(self):
        broker = FakeBroker(self.MESSAGES, qos=1)
        got, main = self._receive("mqtt://127.0.0.1:%d", broker, self._tcp)
        with self.assertRaises(mqtt.MqttError):
            run(main())
        self.assertEqual(broker.pubacks, [1, 2])

    def test_bad_credentials(self):
        got, main = self._receive("mqtt://127.0.0.1:%d", FakeBroker(self.MESSAGES), self._tcp, password="nope")
        with self.assertRaises(PermissionError):
            run(main())

    def test_over_websocket(self):
        seen_headers = {}

        def ws_server(broker):
            async def handle(reader, writer):
                raw = await reader.readuntil(b"\r\n\r\n")
                lines = raw.decode().split("\r\n")
                headers = {k.strip().lower(): v.strip() for k, v in (l.split(":", 1) for l in lines[1:] if ":" in l)}
                seen_headers.update(headers)
                ws = await websocket.server_handshake(reader, writer, headers)
                buf = bytearray()

                async def read(n):
                    while len(buf) < n:
                        _, data = await ws.recv()
                        buf.extend(data)
                    out = bytes(buf[:n])
                    del buf[:n]
                    return out
                await broker.handle_stream(read, ws.send_binary)
                await ws.close()
            return asyncio.start_server(handle, "127.0.0.1", 0)

        got, main = self._receive("ws://127.0.0.1:%d/mqtt", FakeBroker(self.MESSAGES), ws_server)
        with self.assertRaises(mqtt.MqttError):
            run(main())
        self.assertEqual(len(got), 2)
        self.assertEqual(seen_headers.get("sec-websocket-protocol"), "mqtt")
        self.assertRegex(seen_headers["host"], r"^127\.0\.0\.1:\d+$")

    def test_host_header_omits_default_port(self):
        # The URE broker answers "Host: name:443" with a 200 page.
        captured = {}

        async def main():
            async def handle(reader, writer):
                captured["raw"] = (await reader.readuntil(b"\r\n\r\n")).decode()
                writer.close()
            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            orig = asyncio.open_connection

            async def redirect(host, p, **kw):
                return await orig("127.0.0.1", port)
            asyncio.open_connection = redirect
            try:
                with self.assertRaises(websocket.WebSocketError):
                    await websocket.connect("ws://broker.example:80/mqtt", timeout=2)
            finally:
                asyncio.open_connection = orig
                server.close()
        run(main())
        self.assertIn("\r\nHost: broker.example\r\n", captured["raw"])


class Auth(unittest.TestCase):
    def owrx_hash(self, password):
        # Same as owrx.users.HashedPassword in OpenWebRX+ 1.2.x
        salt = os.urandom(32)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return {"encoding": "hash", "value": dk.hex(), "algorithm": "sha256", "salt": salt.hex()}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.owrx = os.path.join(self.tmp.name, "owrx-users.json")
        with open(self.owrx, "w") as fh:
            json.dump([
                {"user": "admin", "enabled": True, "must_change_password": False, "password": self.owrx_hash("s3cret")},
                {"user": "old", "enabled": False, "password": self.owrx_hash("s3cret")},
                {"user": "plain", "enabled": True, "password": {"encoding": "string", "value": "txt"}},
            ], fh)
        self.auth = auth.Authenticator(self.owrx)

    def tearDown(self):
        self.tmp.cleanup()

    def test_openwebrx_accounts(self):
        self.assertTrue(self.auth.verify("admin", "s3cret"))
        self.assertFalse(self.auth.verify("admin", "wrong"))
        self.assertFalse(self.auth.verify("old", "s3cret"))
        self.assertTrue(self.auth.verify("plain", "txt"))
        self.assertEqual(self.auth.accounts_state(), "ok")

    def test_accounts_state(self):
        self.assertEqual(auth.Authenticator(os.path.join(self.tmp.name, "missing.json")).accounts_state(), "unreadable")
        empty = os.path.join(self.tmp.name, "empty.json")
        with open(empty, "w") as fh:
            json.dump([{"user": "x", "enabled": False, "password": {}}], fh)
        self.assertEqual(auth.Authenticator(empty).accounts_state(), "empty")

    def test_password_change_in_openwebrx_applies_at_once(self):
        with open(self.owrx, "w") as fh:
            json.dump([{"user": "admin", "enabled": True, "password": self.owrx_hash("changed")}], fh)
        self.assertFalse(self.auth.verify("admin", "s3cret"))
        self.assertTrue(self.auth.verify("admin", "changed"))

    def test_sessions(self):
        token = self.auth.login("1.2.3.4", "admin", "s3cret")
        self.assertEqual(self.auth.session_user(token), "admin")
        self.auth.logout(token)
        self.assertIsNone(self.auth.session_user(token))

    def test_lockout(self):
        for _ in range(auth.MAX_FAILURES):
            self.assertIsNone(self.auth.login("9.9.9.9", "admin", "bad"))
        self.assertTrue(self.auth.locked_out("9.9.9.9"))
        self.assertIsNone(self.auth.login("9.9.9.9", "admin", "s3cret"))
        self.assertIsNotNone(self.auth.login("1.1.1.1", "admin", "s3cret"))

    def test_owrx_data_directory(self):
        etc = os.path.join(self.tmp.name, "etc")
        os.makedirs(os.path.join(etc, "openwebrx.conf.d"))
        with open(os.path.join(etc, "openwebrx.conf.d", "50-x.conf"), "w") as fh:
            fh.write("[core]\ndata_directory = /srv/owrx\n")
        self.assertEqual(auth.owrx_data_directory(etc), "/srv/owrx")
        self.assertEqual(auth.owrx_data_directory(self.tmp.name), "/var/lib/openwebrx")


class Configuration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(os.path.join(self.tmp.name, "config.json")).load()

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_are_empty(self):
        self.assertFalse(self.cfg["enabled"])
        self.assertEqual((self.cfg["telnet"]["host"], self.cfg["telnet"]["callsign"]), ("", ""))
        self.assertEqual((self.cfg["mqtt"]["url"], self.cfg["mqtt"]["topics"]), ("", []))

    def test_defaults_and_roundtrip(self):
        changed, errors = self.cfg.update({"enabled": True, "source": "mqtt", "mqtt": {
            "url": "wss://broker.example.org/mqtt", "topics": "a/b, c/#", "password": "brokerpw"}})
        self.assertEqual(errors, [])
        self.assertTrue(changed)
        self.cfg.save()
        self.assertEqual(oct(os.stat(self.cfg.path).st_mode & 0o777), "0o600")
        again = Config(self.cfg.path).load()
        self.assertEqual(again["mqtt"]["password"], "brokerpw")
        self.assertEqual(again["mqtt"]["topics"], ["a/b", "c/#"])

    def test_secrets_never_leave(self):
        self.cfg.update({"mqtt": {"password": "brokerpw"}, "telnet": {"password": "nodepw"}})
        self.assertNotIn("brokerpw", json.dumps(self.cfg.redacted()))
        self.assertNotIn("nodepw", json.dumps(self.cfg.redacted()))
        self.assertEqual(set(self.cfg.public()), {"enabled", "max_age_sec", "groups"})
        # Saving the redacted form back keeps the real password.
        self.cfg.update(self.cfg.redacted())
        self.assertEqual(self.cfg["mqtt"]["password"], "brokerpw")

    def test_validation(self):
        _, errors = self.cfg.update({"enabled": True, "source": "telnet"})
        self.assertEqual(len(errors), 2)
        self.assertFalse(self.cfg["enabled"])  # nothing applied
        _, errors = self.cfg.update({"enabled": True, "source": "mqtt", "mqtt": {"url": "http://x", "topics": " , "}})
        self.assertEqual(len(errors), 2)
        _, errors = self.cfg.update({"display": {"max_age_sec": 5}})
        self.assertEqual(len(errors), 1)
        changed, errors = self.cfg.update({"display": {"max_age_sec": 300, "groups": ["CW", "BOGUS"]}})
        self.assertEqual((changed, errors, self.cfg["display"]["groups"]), (False, [], ["CW"]))

    def test_malformed_sections_ignored(self):
        changed, errors = self.cfg.update({"telnet": "x", "mqtt": None, "display": [1]})
        self.assertEqual((changed, errors), (False, []))
        self.assertEqual(self.cfg["telnet"]["port"], 7300)

    def test_server_section_not_editable(self):
        self.cfg.update({"server": {"port": 1}})
        self.assertEqual(self.cfg["server"]["port"], 7374)


class Server(unittest.TestCase):
    """HTTP API and spot WebSocket of a running SpiderServer (no cluster)."""

    async def _request(self, port, method, path, body=None, headers=None):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        data = json.dumps(body).encode() if body is not None else b""
        head = "%s %s HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n" % (method, path, len(data))
        for k, v in (headers or {}).items():
            head += "%s: %s\r\n" % (k, v)
        writer.write(head.encode() + b"\r\n" + data)
        raw = await reader.read()
        writer.close()
        head, _, payload = raw.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        hdrs = {k.lower(): v.strip() for k, v in (l.split(":", 1) for l in lines[1:])}
        return int(lines[0].split()[1]), hdrs, payload

    def test_api_and_stream(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Config(os.path.join(tmp.name, "config.json")).load()
        cfg.data["server"].update(bind="127.0.0.1", port=0)
        owrx_users = os.path.join(tmp.name, "users.json")
        salt = os.urandom(32)
        with open(owrx_users, "w") as fh:
            json.dump([{"user": "admin", "enabled": True, "password": {
                "encoding": "hash", "algorithm": "sha256", "salt": salt.hex(),
                "value": hashlib.pbkdf2_hmac("sha256", b"pass123", salt, 100000).hex()}}], fh)
        authn = auth.Authenticator(owrx_users)

        async def main():
            srv = SpiderServer(cfg, authn, LogBuffer())
            await srv.start()
            port = srv._server.sockets[0].getsockname()[1]
            r = self._request
            H = {"X-Spider-Admin": "1"}

            status, _, body = await r(port, "GET", "/health")
            self.assertEqual((status, json.loads(body)["ok"]), (200, True))
            status, hdrs, _ = await r(port, "GET", "/")
            self.assertEqual((status, hdrs["location"]), (302, "admin/"))
            status, hdrs, body = await r(port, "GET", "/admin/")
            self.assertEqual(status, 200)
            self.assertIn(b"admin.js", body)
            self.assertEqual((await r(port, "GET", "/admin/../server.py"))[0], 404)

            self.assertEqual((await r(port, "GET", "/admin/api/config"))[0], 401)
            self.assertEqual((await r(port, "POST", "/admin/api/login", {"user": "admin", "password": "pass123"}))[0], 403)
            self.assertEqual((await r(port, "POST", "/admin/api/login", {"user": "admin", "password": "x"}, H))[0], 401)
            status, hdrs, _ = await r(port, "POST", "/admin/api/login", {"user": "admin", "password": "pass123"}, H)
            self.assertEqual(status, 200)
            cookie = hdrs["set-cookie"].split(";")[0]
            self.assertIn("HttpOnly", hdrs["set-cookie"])
            A = dict(H, Cookie=cookie)

            # A browser connects before the cluster is enabled.
            ws = await websocket.connect("ws://127.0.0.1:%d/spots" % port)
            first = json.loads((await ws.recv())[1])
            self.assertEqual(first, {"type": "config", "config": {"enabled": False, "max_age_sec": 600,
                                                                  "groups": ["CW", "DIGITAL", "PHONE"]}})

            status, _, body = await r(port, "POST", "/admin/api/config",
                                      {"display": {"max_age_sec": 120, "groups": ["CW"]}}, A)
            self.assertEqual(status, 200)
            pushed = json.loads((await ws.recv())[1])
            self.assertEqual(pushed["config"]["groups"], ["CW"])

            spot = spots.make_spot(14025000, "K1ABC", mode="CW", source="test")
            await srv.publish(spot)
            msg = json.loads((await ws.recv())[1])
            self.assertEqual((msg["type"], msg["spot"]["call"]), ("spot", "K1ABC"))

            # A later browser gets the backlog (only when enabled).
            srv.config.data["enabled"] = True
            ws2 = await websocket.connect("ws://127.0.0.1:%d/spots" % port)
            await ws2.recv()
            backlog = json.loads((await ws2.recv())[1])
            self.assertEqual([s["call"] for s in backlog["spots"]], ["K1ABC"])

            status, _, body = await r(port, "GET", "/admin/api/status", None, A)
            st = json.loads(body)
            self.assertEqual((st["browsers"], st["recent"][0]["call"]), (2, "K1ABC"))

            status, hdrs, _ = await r(port, "POST", "/admin/api/logout", {}, A)
            self.assertEqual((await r(port, "GET", "/admin/api/config", None, A))[0], 401)
            await ws.close()
            await ws2.close()
            await srv.stop()
        run(main())


class Websocket(unittest.TestCase):
    def test_frames(self):
        key = b"\x01\x02\x03\x04"
        self.assertEqual(websocket._mask(websocket._mask(b"hello world", key), key), b"hello world")
        self.assertEqual(websocket.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")
        big = websocket.encode_frame(websocket.OP_BINARY, b"x" * 70000, mask=False)
        self.assertEqual(big[1], 127)


if __name__ == "__main__":
    unittest.main()
