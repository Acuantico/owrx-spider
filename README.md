# OpenWebRX+ Spider (DX Cluster Waterfall Spots)

Spider is a production-ready DX Cluster overlay for OpenWebRX+. It adds a lightweight, non-intrusive visual layer on top of the waterfall that shows live spots from DXSpider/CC-Cluster style telnet feeds. A dedicated backend service (spiderd) handles the telnet connection, parses standard DX spot lines, normalizes them into JSON, and streams them to the browser over a local WebSocket. The frontend renders thin frequency markers with compact callsign labels, color-coded by mode, and automatically fades out stale spots to keep the display clean.

This package is intended to be installed as a complete solution: frontend plugin, backend service, and OpenWebRX+ settings integration. The installer applies the required core integration so configuration is available in the OpenWebRX settings UI.

## Contents

- Receiver plugin: `receiver/spider/`
- Backend service: `backend/spiderd/`
- systemd unit: `systemd/spiderd.service`
- Install script: `scripts/install_spider.sh`
- Init sample: `receiver/init.js.sample`

## Install

Run the installer script from the repo root:

```
cd /path/to/owrx-spider
sudo bash scripts/install_spider.sh
```

This installs the frontend plugin, backend service, systemd unit, and default configuration.

Note: The installer patches OpenWebRX+ core files to expose the Spider settings in the UI.
Backups are created next to the modified files with a `.bak-YYYYmmddHHMMSS` suffix.
If you later upgrade OpenWebRX+, re-run the installer to re-apply the patches.

### If installation fails (paths)

The installer auto-detects OpenWebRX paths. If your installation uses custom locations, edit
`scripts/install_spider.sh` and adjust these variables near the top:

- `PYROOT` (OpenWebRX python package root, e.g. `/usr/lib/python3/dist-packages/owrx`)
- `WEBROOT` (OpenWebRX web root, e.g. `/usr/lib/python3/dist-packages/htdocs`)
- `BACKEND_DST_DIR` (default: `/opt/spiderd`)

After updating the script, rerun the installer.

## Configure

Configure the DX Cluster settings from the OpenWebRX+ web UI:
Settings -> Spotting and reporting -> Waterfall spots server.

The integration allows the UI to:
- Enable/disable the spiderd service
- Write `/opt/spiderd/spiderd.conf` from the UI fields

For plain HTTP installs, the default WebSocket connection works without TLS or proxy.
If your OpenWebRX+ is served over HTTPS, use a reverse proxy for `/spiderws/` or set a
`wss://` endpoint in `window.spider_config_global`.

## License

GNU Affero General Public License v3.0 (AGPL-3.0)

## Author

Acuantico Power - https://acuanticopower.com

## Disclaimer

This software is provided "as is", without warranty of any kind. Use at your own risk.















# OpenWebRX+ Spider (Spots de DX Cluster en la cascada)

Spider es una superposición de DX Cluster lista para producción para OpenWebRX+. Añade una capa visual ligera y no intrusiva sobre la cascada que muestra en tiempo real los spots procedentes de feeds telnet tipo DXSpider/CC-Cluster. Un servicio backend dedicado (spiderd) gestiona la conexión telnet, analiza las líneas estándar de spots DX, las normaliza a JSON y las transmite al navegador mediante un WebSocket local. El frontend renderiza marcadores de frecuencia finos con etiquetas compactas de indicativos, codificados por color según el modo, y atenúa automáticamente los spots antiguos para mantener la visualización limpia.

Este paquete está pensado para instalarse como una solución completa: plugin frontend, servicio backend e integración con la configuración de OpenWebRX+. El instalador aplica la integración necesaria en el núcleo para que la configuración esté disponible en la interfaz de ajustes de OpenWebRX.

## Contenido
- Plugin del receptor: receiver/spider/
- Servicio backend: backend/spiderd/
- Unidad systemd: systemd/spiderd.service
- Script de instalación: scripts/install_spider.sh
- Ejemplo de inicialización: receiver/init.js.sample

## Instalación
Ejecuta el script de instalación desde la raíz del repositorio:

cd /ruta/a/owrx-spider  
sudo bash scripts/install_spider.sh

Esto instala el plugin frontend, el servicio backend, la unidad systemd y la configuración por defecto.

Nota: el instalador modifica archivos del núcleo de OpenWebRX+ para exponer los ajustes de Spider en la interfaz web. Se crean copias de seguridad junto a los archivos modificados con el sufijo .bak-YYYYmmddHHMMSS.

## Si la instalación falla (rutas)
El instalador detecta automáticamente las rutas de OpenWebRX. Si tu instalación utiliza ubicaciones personalizadas, edita scripts/install_spider.sh y ajusta estas variables cerca del inicio del archivo:
- PYROOT (raíz del paquete Python de OpenWebRX, por ejemplo /usr/lib/python3/dist-packages/owrx)
- WEBROOT (raíz web de OpenWebRX, por ejemplo /usr/lib/python3/dist-packages/htdocs)
- BACKEND_DST_DIR (por defecto: /opt/spiderd)

Después de actualizar el script, vuelve a ejecutar el instalador.

## Configuración
Configura los ajustes del DX Cluster desde la interfaz web de OpenWebRX+:
Settings -> Spotting and reporting -> Waterfall spots server

La integración permite:
- Activar o desactivar el servicio spiderd
- Escribir /opt/spiderd/spiderd.conf desde los campos de la interfaz

En instalaciones HTTP sin cifrado, la conexión WebSocket por defecto funciona sin TLS ni proxy.  
Si OpenWebRX+ se sirve por HTTPS, utiliza un proxy inverso para /spiderws/ o define un endpoint wss:// en window.spider_config_global.

## Licencia
GNU Affero General Public License v3.0 (AGPL-3.0)

## Autor
Acuantico Power – https://acuanticopower.com

## Descargo de responsabilidad

Este software se proporciona "tal cual", sin garantias de ningun tipo. El uso es bajo tu propia responsabilidad.
