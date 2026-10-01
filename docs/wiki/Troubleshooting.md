# Troubleshooting

## The configuration page does not open

- Check that spiderd is running:
  - package installs: `systemctl status owrx-spider`;
  - Docker: `docker logs <container> | grep spiderd`.
- Check that TCP port 7374 is reachable from your computer (firewall, port
  forwarding).
- `http://<host>:7374/health` should answer `{"ok": true, …}`.

## "spiderd cannot read the OpenWebRX+ accounts file"

spiderd must run as the same system user as OpenWebRX+. Otherwise it cannot
read the file that holds the OpenWebRX+ administrator accounts.

- Package installs: run `sudo ./install.sh` again. It sets the service
  account to the one used by `openwebrx.service`.
- If OpenWebRX+ keeps its data somewhere unusual, spiderd finds it through
  `data_directory` in `/etc/openwebrx/openwebrx.conf`, or in a file in
  `/etc/openwebrx/openwebrx.conf.d/`.

## "OpenWebRX+ has no administrator account yet"

Create one, then log in with it:

```sh
sudo openwebrx admin adduser <name>
# Docker:
docker exec -it <container> openwebrx admin adduser <name>
```

## The status shows `error`

The message next to the state comes from the connection.

| Message | Meaning |
| --- | --- |
| `Name or service not known` | The host name is wrong, or the server has no DNS |
| `Connection refused` / timeout | Wrong port, or the cluster or broker is down or firewalled |
| `login refused: …` | The telnet node rejected the callsign or password. Check them |
| `broker refused connection: bad user name or password` / `not authorized` | Wrong MQTT credentials or permissions |
| `handshake rejected: HTTP/1.1 …` | Wrong WebSocket path in the MQTT URL (often `/mqtt`) |
| `no data from cluster for 300 s` | The node stopped sending. spiderd reconnects by itself |

spiderd retries on its own. It waits 3 seconds at first, doubling up to one
minute.

## Connected, but no spots on the waterfall

- In **Latest spots** on the configuration page, check that spots are
  arriving.
- The receiver only draws spots inside the frequency range currently shown.
  Spots on other bands are received, but not visible there.
- Check **Show these spots** on the configuration page.
- Check the **Show DX cluster spots** box in the receiver's Settings section.
- Open the browser console (F12) on the receiver page. A message like
  `WebSocket connection to 'ws://…:7374/spots' failed` means the browser cannot
  reach spiderd. See [[HTTPS and reverse proxies|HTTPS-and-reverse-proxies]].

## The checkbox does not appear in the receiver

- Make sure the connection is **Enabled** on the configuration page. When it
  is disabled, the plugin hides itself.
- Make sure `init.js` contains `Plugins.load('spider');`.
- Raspberry Pi image: run `sudo systemctl restart varnish`.
- Reload the receiver page while bypassing the browser cache (Ctrl+Shift+R).

## Logs

```sh
journalctl -u owrx-spider -f              # package installs
docker logs -f <container> | grep spiderd  # Docker
```

The last log lines are also shown on the configuration page, under
**Service log**.
