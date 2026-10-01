# Installation (OpenWebRX+ from packages)

This page is for OpenWebRX+ installed with `apt` on Debian, Ubuntu or
Raspberry Pi OS, where it runs as the systemd service `openwebrx`. For Docker,
see [[Installation with Docker|Installation-with-Docker]].

## Requirements

- OpenWebRX+ with the plugin loader (any current 1.2.x release).
- systemd.
- Python 3.7 or newer. It is already installed, because OpenWebRX+ uses it.
- `git`, or another way to download the repository.

## Install

```sh
git clone https://github.com/Acuantico/owrx-spider.git
cd owrx-spider
sudo ./install.sh
```

At the end, the installer prints the address of the configuration page.
Continue with [[Configuration]].

### Options

| Option | Use |
| --- | --- |
| `--htdocs DIR` | OpenWebRX+ web folder, if it is not found automatically |
| `--no-start` | Install without starting the service now |

## What the installer does

| Item | Location |
| --- | --- |
| Receiver plugin | `<htdocs>/plugins/receiver/spider/` |
| Plugin loading | adds `Plugins.load('spider');` to `<htdocs>/plugins/receiver/init.js` |
| spiderd program | `/opt/owrx-spider/spiderd/` |
| Service | `/etc/systemd/system/owrx-spider.service` |
| Settings | `/var/lib/owrx-spider/config.json` |

`<htdocs>` is usually `/usr/lib/python3/dist-packages/htdocs`.

About `init.js`:

- If you have no `init.js` yet, the installer creates it.
- If you already have one, the installer appends a single line and keeps a
  backup next to it (`init.js.bak-<date>`). Your other plugins are not touched.

About the service:

- It runs as the same system account as OpenWebRX+ (normally `openwebrx`), so
  it can read the OpenWebRX+ administrator accounts used to log in.
- It is bound to `openwebrx.service`: it starts when OpenWebRX+ starts, and
  stops or restarts when OpenWebRX+ does. You do not need to manage it
  separately.

## Network

- Receiver pages connect to spiderd on **TCP port 7374**. Open or forward
  that port wherever port 8073 (OpenWebRX+) is reachable.
- If OpenWebRX+ is published over HTTPS, read
  [[HTTPS and reverse proxies|HTTPS-and-reverse-proxies]].

## Raspberry Pi image (varnish cache)

The OpenWebRX+ Raspberry Pi image serves the web interface through a varnish
cache. After installing, run:

```sh
sudo systemctl restart varnish
```

Otherwise the plugin may not appear until the cache expires.

## Checking the service

```sh
systemctl status owrx-spider
journalctl -u owrx-spider -f
```
