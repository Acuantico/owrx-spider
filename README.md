# OpenWebRX+ Spider — DX cluster spots on the waterfall

*[Español más abajo](#español)*

Spider shows live DX cluster spots on the OpenWebRX+ waterfall: the callsign
of each station at its frequency, colored by mode (CW cyan, digital magenta,
phone yellow).

- **`spider` receiver plugin**: a standard plugin for the official OpenWebRX+
  plugin loader. No OpenWebRX+ file is modified.
- **`spiderd` service**: runs next to OpenWebRX+ and starts and stops with
  it. It keeps one connection to a **telnet DX cluster** (DXSpider,
  CC-Cluster, AR-Cluster…) or an **MQTT broker** (`mqtt://`, `mqtts://`,
  `ws://`, `wss://`), and forwards the spots to the receiver pages.
- **Configuration page**: `http://<receiver>:7374/admin/`. Log in with the
  OpenWebRX+ administrator user and password of that installation. Nothing is
  preset: each installation enters the cluster it wants to use.

`spiderd` needs only Python 3.7+ (standard library). Tested with OpenWebRX+
1.2.125 (Debian packages and Docker).

## Quick start (OpenWebRX+ installed from packages)

```sh
git clone https://github.com/Acuantico/owrx-spider.git
cd owrx-spider
sudo ./install.sh
```

Then open `http://<receiver>:7374/admin/`, enter your cluster and tick
**Enabled**. Receivers must be able to reach TCP port 7374.

## Documentation

See the **[wiki](https://github.com/Acuantico/owrx-spider/wiki)**. The same
pages are in [`docs/wiki/`](docs/wiki/):

- [Installation](docs/wiki/Installation.md)
- [Installation with Docker](docs/wiki/Installation-with-Docker.md)
- [Configuration](docs/wiki/Configuration.md)
- [MQTT message format](docs/wiki/MQTT-message-format.md)
- [HTTPS and reverse proxies](docs/wiki/HTTPS-and-reverse-proxies.md)
- [Troubleshooting](docs/wiki/Troubleshooting.md)
- [Updating and uninstalling](docs/wiki/Updating-and-uninstalling.md)

## Development

- Tests: `python3 -m unittest discover -s tests` (standard library only).
- `lab/`: isolated Docker laboratory with a clean OpenWebRX+, a synthetic SDR,
  a fake telnet cluster and a local MQTT broker. Start it with
  `cd lab && ./prepare.sh && docker compose up -d`, then open:
  - receiver: `http://127.0.0.1:18174/`
  - spiderd: `http://127.0.0.1:7374/admin/` (user `admin`, password `spider-lab-pass`)
- `lab/native/test.sh`: tests `install.sh` and `uninstall.sh` on a clean
  package-based OpenWebRX+ with systemd.

## License

GNU Affero General Public License v3.0 (AGPL-3.0)

## Author

Acuantico Power - https://acuanticopower.com

## Disclaimer

This software is provided "as is", without warranty of any kind. Use at your own risk.

---

## Español

Spider muestra en tiempo real los spots de un DX cluster sobre la cascada de
OpenWebRX+: el indicativo de cada estación en su frecuencia, coloreado por modo
(CW cian, digitales magenta, fonía amarillo).

- **Plugin de receptor `spider`**: plugin estándar del cargador oficial de
  plugins de OpenWebRX+. No modifica ningún archivo de OpenWebRX+.
- **Servicio `spiderd`**: se ejecuta junto a OpenWebRX+ y arranca y se detiene
  con él. Mantiene una conexión con un **DX cluster por telnet** o con un
  **broker MQTT**, y reparte los spots a los receptores.
- **Página de configuración**: `http://<receptor>:7374/admin/`. Se entra con el
  usuario y la contraseña de administrador de OpenWebRX+ de esa instalación. No
  hay datos de cluster precargados: cada instalación pone el cluster que
  quiera usar.

Instalación rápida: `git clone …`, `cd owrx-spider` y `sudo ./install.sh`.
Después abre la página de configuración. La documentación completa (en inglés)
está en la [wiki](https://github.com/Acuantico/owrx-spider/wiki) y en
[`docs/wiki/`](docs/wiki/).

Licencia AGPL-3.0 · Acuantico Power - https://acuanticopower.com · Se
proporciona "tal cual", sin garantías de ningún tipo.
