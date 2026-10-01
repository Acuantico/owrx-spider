#!/usr/bin/env bash
# Install or update owrx-spider on an OpenWebRX+ system installed from
# packages (Debian/Ubuntu/Raspberry Pi OS). Run again to update: the
# configuration in /var/lib/owrx-spider is kept.
#
#   sudo ./install.sh [--htdocs DIR] [--no-start]
#
# Nothing in OpenWebRX+ itself is modified: the receiver plugin goes to
# htdocs/plugins/receiver/spider and is loaded from plugins/receiver/init.js,
# the official place for that. spiderd runs as its own systemd service tied
# to openwebrx.service.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR=/opt/owrx-spider
DATA_DIR=/var/lib/owrx-spider
UNIT=owrx-spider.service
UNIT_DST=/etc/systemd/system/$UNIT
HTDOCS=""
START=1

say() { echo "[owrx-spider] $*"; }
die() { echo "[owrx-spider] ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --htdocs) HTDOCS="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "unknown option $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "run as root (sudo $0)"
command -v python3 >/dev/null || die "python3 not found"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 7))' || die "python3 >= 3.7 required"
command -v systemctl >/dev/null || die "systemd is required (for Docker see the README)"

# Locate a python package of OpenWebRX+ without picking up this directory.
find_pkg() {
  (cd / && python3 - "$1" <<'PY'
import importlib.util, os, sys
spec = importlib.util.find_spec(sys.argv[1])
if spec and spec.submodule_search_locations:
    print(list(spec.submodule_search_locations)[0])
PY
  ) 2>/dev/null || true
}

if [ -z "$HTDOCS" ]; then
  HTDOCS="$(find_pkg htdocs)"
  for candidate in /usr/lib/python3/dist-packages/htdocs /opt/openwebrx/htdocs /usr/share/openwebrx/htdocs; do
    [ -n "$HTDOCS" ] && break
    [ -d "$candidate" ] && HTDOCS="$candidate"
  done
fi
[ -n "$HTDOCS" ] && [ -f "$HTDOCS/plugins.js" ] \
  || die "OpenWebRX+ htdocs not found (with the plugin loader). Use --htdocs DIR"

# Run as the same account as OpenWebRX+ so its users.json is readable.
OWRX_UNIT_FOUND=0
OWRX_USER=openwebrx
if systemctl cat openwebrx.service >/dev/null 2>&1; then
  OWRX_UNIT_FOUND=1
  unit_user="$(systemctl show -p User --value openwebrx.service 2>/dev/null || true)"
  [ -n "$unit_user" ] && OWRX_USER="$unit_user"
fi
id "$OWRX_USER" >/dev/null 2>&1 || die "user '$OWRX_USER' (OpenWebRX+ service account) does not exist"
OWRX_GROUP="$(id -gn "$OWRX_USER")"

say "OpenWebRX+ web root: $HTDOCS"
say "service account:      $OWRX_USER:$OWRX_GROUP"

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
say "installing spiderd to $APP_DIR"
rm -rf "$APP_DIR/spiderd"
install -d -m 755 "$APP_DIR"
cp -r "$SRC/spiderd" "$APP_DIR/spiderd"
find "$APP_DIR/spiderd" -name __pycache__ -prune -exec rm -rf {} +
find "$APP_DIR" -type d -exec chmod 755 {} +
find "$APP_DIR" -type f -exec chmod 644 {} +

PLUGIN_DIR="$HTDOCS/plugins/receiver/spider"
say "installing the receiver plugin to $PLUGIN_DIR"
rm -rf "$PLUGIN_DIR"
install -d -m 755 "$PLUGIN_DIR"
install -m 644 "$SRC/plugin/spider/spider.js" "$SRC/plugin/spider/spider.css" "$PLUGIN_DIR/"

INIT_JS="$HTDOCS/plugins/receiver/init.js"
if [ ! -f "$INIT_JS" ]; then
  say "creating $INIT_JS"
  install -m 644 "$SRC/plugin/init.js.sample" "$INIT_JS"
elif ! grep -Eq "Plugins\.load\(\s*['\"]spider['\"]\s*\)" "$INIT_JS"; then
  cp -a "$INIT_JS" "$INIT_JS.bak-$(date +%Y%m%d%H%M%S)"
  printf "\n// DX cluster spots (owrx-spider)\nPlugins.load('spider');\n" >> "$INIT_JS"
  say "added Plugins.load('spider') to $INIT_JS (backup saved next to it)"
else
  say "$INIT_JS already loads the plugin"
fi

install -d -m 750 "$DATA_DIR"
chown -R "$OWRX_USER:$OWRX_GROUP" "$DATA_DIR"

say "installing $UNIT"
sed -e "s/^User=.*/User=$OWRX_USER/" -e "s/^Group=.*/Group=$OWRX_GROUP/" \
  "$SRC/packaging/systemd/$UNIT" > "$UNIT_DST"
if [ "$OWRX_UNIT_FOUND" -eq 0 ]; then
  # No openwebrx.service to follow: run as a normal boot-time service.
  sed -i -e '/^PartOf=/d' -e 's/^WantedBy=openwebrx.service/WantedBy=multi-user.target/' "$UNIT_DST"
  say "openwebrx.service not found: $UNIT will start at boot on its own"
fi
chmod 644 "$UNIT_DST"
systemctl daemon-reload
systemctl reenable "$UNIT" >/dev/null 2>&1

if [ "$START" -eq 1 ]; then
  if [ "$OWRX_UNIT_FOUND" -eq 0 ] || systemctl is-active --quiet openwebrx.service; then
    systemctl restart "$UNIT"
  else
    say "openwebrx.service is not running; $UNIT will start together with it"
  fi
fi

PORT="$(cd "$APP_DIR" && python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1]))["server"]["port"])
except Exception: print(7374)' "$DATA_DIR/config.json")"
HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
say "done. Configure the cluster at  http://${HOST:-<this-host>}:${PORT}/admin/"
say "log in with your OpenWebRX+ administrator account."
say "receivers need to reach TCP port $PORT (firewall / port forwarding)."
if systemctl is-active --quiet varnish 2>/dev/null; then
  say "varnish is caching the web UI: run 'systemctl restart varnish' to see the plugin now."
fi
