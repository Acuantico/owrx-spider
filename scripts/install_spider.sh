#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

SRC_PLUGIN_DIR="${ROOT_DIR}/receiver/spider"
BACKEND_SRC_DIR="${ROOT_DIR}/backend/spiderd"
BACKEND_DST_DIR="/opt/spiderd"
SYSTEMD_SRC="${ROOT_DIR}/systemd/spiderd.service"
SYSTEMD_DST="/etc/systemd/system/spiderd.service"

PYROOT="$(ROOT_DIR="${ROOT_DIR}" python3 - <<'PY'
import importlib.util
import os
import sys

root_dir = os.environ.get("ROOT_DIR", "")
sys.path = [p for p in sys.path if p not in ("", root_dir)]

def resolve(name):
    spec = importlib.util.find_spec(name)
    if spec is None:
        return ""
    if spec.submodule_search_locations:
        return list(spec.submodule_search_locations)[0]
    if spec.origin:
        return os.path.dirname(spec.origin)
    return ""

print(resolve("owrx"))
PY
 2>/dev/null || true)"

WEBROOT="$(ROOT_DIR="${ROOT_DIR}" python3 - <<'PY'
import importlib.util
import os
import sys

root_dir = os.environ.get("ROOT_DIR", "")
sys.path = [p for p in sys.path if p not in ("", root_dir)]

def resolve(name):
    spec = importlib.util.find_spec(name)
    if spec is None:
        return ""
    if spec.submodule_search_locations:
        return list(spec.submodule_search_locations)[0]
    if spec.origin:
        return os.path.dirname(spec.origin)
    return ""

print(resolve("htdocs"))
PY
 2>/dev/null || true)"

if [ -n "${PYROOT}" ] && [[ "${PYROOT}" == "${ROOT_DIR}"* ]]; then
  PYROOT=""
fi
if [ -z "${PYROOT}" ] || [ ! -d "${PYROOT}" ]; then
  if [ -d "/usr/lib/python3/dist-packages/owrx" ]; then
    PYROOT="/usr/lib/python3/dist-packages/owrx"
  else
    echo "[spider] Cannot find OpenWebRX+ python package root." >&2
    exit 1
  fi
fi

if [ -n "${WEBROOT}" ] && [[ "${WEBROOT}" == "${ROOT_DIR}"* ]]; then
  WEBROOT=""
fi
if [ -z "${WEBROOT}" ] || [ ! -d "${WEBROOT}" ]; then
  if [ -d "/usr/lib/python3/dist-packages/htdocs" ]; then
    WEBROOT="/usr/lib/python3/dist-packages/htdocs"
  elif [ -d "/usr/share/openwebrx/htdocs" ]; then
    WEBROOT="/usr/share/openwebrx/htdocs"
  else
    echo "[spider] Cannot find OpenWebRX+ web root." >&2
    exit 1
  fi
fi

DST_PLUGIN_DIR="${WEBROOT}/plugins/receiver/spider"
INIT_JS="${WEBROOT}/plugins/receiver/init.js"

say() {
  echo "[spider] $*"
}

backup_file() {
  local file="$1"
  local ts
  ts="$(date +%Y%m%d%H%M%S)"
  cp -a "$file" "${file}.bak-${ts}"
  say "Backup created: ${file}.bak-${ts}"
}

ensure_init_js() {
  if [[ ! -f "${INIT_JS}" ]]; then
    say "Creating ${INIT_JS}";
    cat > "${INIT_JS}" <<'EOF'
// Receiver plugins initialization.
// Load local plugins here.

Plugins.load('spider');
EOF
    return
  fi

  if ! grep -q "Plugins.load('spider')" "${INIT_JS}"; then
    say "Enabling spider plugin in ${INIT_JS}";
    printf "\nPlugins.load('spider');\n" >> "${INIT_JS}"
  else
    say "Spider plugin already enabled in ${INIT_JS}";
  fi
}

install_frontend() {
  say "Installing frontend plugin to ${DST_PLUGIN_DIR}"
  install -d "${DST_PLUGIN_DIR}"
  cp -a "${SRC_PLUGIN_DIR}/." "${DST_PLUGIN_DIR}/"
}

patch_reporting_settings() {
  local reporting_py="${PYROOT}/controllers/settings/reporting.py"
  if [[ ! -f "${reporting_py}" ]]; then
    say "Reporting controller not found: ${reporting_py}"
    exit 1
  fi

  if ! grep -q "spider_enabled" "${reporting_py}"; then
    backup_file "${reporting_py}"
  fi

  say "Patching Spider settings into ${reporting_py}"
  REPORTING_PY="${reporting_py}" python3 - <<'PY'
from pathlib import Path
import os

path = Path(os.environ["REPORTING_PY"])
data = path.read_text(encoding="utf-8")

if "spider_enabled" in data:
    raise SystemExit(0)

block = """
            Section(
                "DX Cluster (Spider) settings",
                CheckboxInput(
                    "spider_enabled",
                    "Enable DX Cluster overlay",
                ),
                TextInput(
                    "spider_host",
                    "Cluster host",
                ),
                NumberInput(
                    "spider_port",
                    "Cluster port",
                ),
                TextInput(
                    "spider_callsign",
                    "Cluster callsign",
                ),
                PasswordInput(
                    "spider_password",
                    "Cluster password",
                ),
            ),
"""

marker = '            Section(\n                "MQTT settings",'
if marker in data:
    data = data.replace(marker, block + marker, 1)
else:
    marker = '            Section(\n                "RigControl settings",'
    if marker in data:
        data = data.replace(marker, block + marker, 1)
    else:
        data = data.replace("        ]\n", block + "        ]\n", 1)

path.write_text(data, encoding="utf-8")
PY

  if ! grep -q "spider_enabled" "${reporting_py}"; then
    say "Failed to patch Spider settings into ${reporting_py}"
    exit 1
  fi
}

patch_defaults() {
  local defaults_py="${PYROOT}/config/defaults.py"
  if [[ ! -f "${defaults_py}" ]]; then
    say "Defaults file not found: ${defaults_py}"
    exit 1
  fi

  if ! grep -q "spider_enabled" "${defaults_py}"; then
    backup_file "${defaults_py}"
  fi

  say "Ensuring spider defaults in ${defaults_py}"
  DEFAULTS_PY="${defaults_py}" python3 - <<'PY'
from pathlib import Path
import os
import re

path = Path(os.environ["DEFAULTS_PY"])
data = path.read_text(encoding="utf-8")

if "spider_enabled" in data:
    raise SystemExit(0)

block = """
    spider_enabled=False,
    spider_callsign="N0CALL",
    spider_host="dxspider.example.net",
    spider_port=7300,
    spider_password="",
"""
data = re.sub(r"\n\)\s*$", "\n" + block + ")\n", data)
path.write_text(data, encoding="utf-8")
PY

  if ! grep -q "spider_enabled" "${defaults_py}"; then
    say "Failed to add spider defaults into ${defaults_py}"
    exit 1
  fi
}

install_backend() {
  say "Installing backend to ${BACKEND_DST_DIR}"
  install -d "${BACKEND_DST_DIR}"
  cp -a "${BACKEND_SRC_DIR}/spiderd.py" "${BACKEND_DST_DIR}/"
  cp -a "${BACKEND_SRC_DIR}/requirements.txt" "${BACKEND_DST_DIR}/"

  if [[ ! -f "${BACKEND_DST_DIR}/spiderd.conf" ]]; then
    say "Creating ${BACKEND_DST_DIR}/spiderd.conf"
    cp -a "${BACKEND_SRC_DIR}/spiderd.conf" "${BACKEND_DST_DIR}/spiderd.conf"
  else
    say "Keeping existing ${BACKEND_DST_DIR}/spiderd.conf"
  fi

  if [[ ! -d "${BACKEND_DST_DIR}/venv" ]]; then
    say "Creating virtual environment"
    python3 -m venv "${BACKEND_DST_DIR}/venv"
  fi

  say "Installing Python requirements"
  "${BACKEND_DST_DIR}/venv/bin/pip" install -r "${BACKEND_DST_DIR}/requirements.txt"
}

install_systemd() {
  say "Installing systemd unit"
  install -m 644 "${SYSTEMD_SRC}" "${SYSTEMD_DST}"
  systemctl daemon-reload
  systemctl enable --now spiderd.service
}

main() {
  if [[ ! -d "${SRC_PLUGIN_DIR}" ]]; then
    echo "Source plugin directory not found: ${SRC_PLUGIN_DIR}" >&2
    exit 1
  fi
  if [[ ! -d "${BACKEND_SRC_DIR}" ]]; then
    echo "Backend source directory not found: ${BACKEND_SRC_DIR}" >&2
    exit 1
  fi
  if [[ ! -f "${SYSTEMD_SRC}" ]]; then
    echo "Systemd unit file not found: ${SYSTEMD_SRC}" >&2
    exit 1
  fi

  install_frontend
  ensure_init_js
  patch_reporting_settings
  patch_defaults
  install_backend
  install_systemd

  say "Installation complete"
}

main "$@"
