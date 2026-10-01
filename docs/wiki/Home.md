# OpenWebRX+ Spider

Spider shows live **DX cluster spots on the OpenWebRX+ waterfall**: a small
label with the callsign at the top of the waterfall, starting at the spotted
frequency, marked with the color of its mode. Labels fade as spots get older
and are stacked in rows so neighbours do not overlap.

| Color | Spots |
| --- | --- |
| Cyan | CW |
| Magenta | Digital modes (FT8, FT4, RTTY, PSK…) |
| Yellow | Phone (SSB, AM, FM…) |

## How it works

Spider has two parts:

- **The `spider` receiver plugin.** A standard plugin for the official
  OpenWebRX+ plugin loader. It is installed in `htdocs/plugins/receiver/spider`
  and loaded from `htdocs/plugins/receiver/init.js`. It does not modify any
  OpenWebRX+ file.
- **The `spiderd` service.** A small program that runs next to OpenWebRX+ and
  starts and stops together with it. It keeps a single connection to the
  cluster you choose and forwards the spots to every open receiver page. It
  also serves the **configuration page** where the administrator sets up the
  cluster.

```
 Telnet DX cluster ─┐                         ┌─► receiver page
                    ├─► spiderd (port 7374) ──┼─► receiver page
 MQTT broker ───────┘   /admin/   /spots      └─► …
```

Supported cluster sources:

- **Telnet DX clusters**: DXSpider, CC-Cluster, AR-Cluster and compatible nodes.
- **MQTT brokers** publishing JSON spots, over `mqtt://`, `mqtts://`, `ws://`
  or `wss://`.

Nothing is preset: each installation enters the cluster it wants to use.

`spiderd` needs only Python 3.7 or newer and its standard library. There is
nothing to install with `pip`, so it runs anywhere OpenWebRX+ runs, including
its Docker image.

## Pages

1. [[Installation]] — OpenWebRX+ installed from packages (Debian, Ubuntu, Raspberry Pi)
2. [[Installation with Docker|Installation-with-Docker]]
3. [[Configuration]] — logging in and setting up the cluster
4. [[MQTT message format|MQTT-message-format]]
5. [[HTTPS and reverse proxies|HTTPS-and-reverse-proxies]]
6. [[Troubleshooting]]
7. [[Updating and uninstalling|Updating-and-uninstalling]]

Tested with OpenWebRX+ 1.2.125 (Debian 12 packages and the
`slechev/openwebrxplus` Docker image) and Python 3.7 – 3.13.
