#!/usr/bin/env bash
# Remove owrx-spider from a package-based OpenWebRX+ system.
#
#   sudo ./uninstall.sh [--htdocs DIR] [--purge]
#
# --purge also deletes the configuration in /var/lib/owrx-spider.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR=/opt/owrx-spider
DATA_DIR=/var/lib/owrx-spider
UNIT=owrx-spider.service
HTDOCS=""
PURGE=0

say() { echo "[owrx-spider] $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --htdocs) HTDOCS="$2"; shift 2 ;;
    --purge) PURGE=1; shift ;;
    *) echo "unknown option $1" >&2; exit 1 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

if [ -z "$HTDOCS" ]; then
  HTDOCS="$(cd / && python3 -c 'import importlib.util as u; s=u.find_spec("htdocs"); print(list(s.submodule_search_locations)[0] if s else "")' 2>/dev/null || true)"
  [ -z "$HTDOCS" ] && [ -d /usr/lib/python3/dist-packages/htdocs ] && HTDOCS=/usr/lib/python3/dist-packages/htdocs
fi

systemctl disable --now "$UNIT" >/dev/null 2>&1 || true
rm -f "/etc/systemd/system/$UNIT"
systemctl daemon-reload
rm -rf "$APP_DIR"
say "service removed"

if [ -n "$HTDOCS" ]; then
  rm -rf "$HTDOCS/plugins/receiver/spider"
  INIT_JS="$HTDOCS/plugins/receiver/init.js"
  if [ -f "$INIT_JS" ] && cmp -s "$INIT_JS" "$SRC/plugin/init.js.sample"; then
    rm -f "$INIT_JS"  # created by install.sh and never edited
  elif [ -f "$INIT_JS" ]; then
    sed -i -E "/^\/\/ DX cluster spots \(owrx-spider\)$/d; /Plugins\.load\(\s*['\"]spider['\"]\s*\);?/d" "$INIT_JS"
  fi
  say "receiver plugin removed"
fi

if [ "$PURGE" -eq 1 ]; then
  rm -rf "$DATA_DIR"
  say "configuration deleted"
else
  say "configuration kept in $DATA_DIR (use --purge to delete it)"
fi
