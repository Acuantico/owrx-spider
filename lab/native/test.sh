#!/bin/sh
# End-to-end test of install.sh / uninstall.sh on a clean package-based
# OpenWebRX+ (Debian 12 + systemd, in a container). Sequence:
#   1. install.sh on the clean system
#   2. start/stop/restart coupling with openwebrx.service, and a "reboot"
#   3. run install.sh again (update), then uninstall.sh and --purge
set -eu
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"
C=owrx-spider-native
X() { docker exec "$C" sh -c "$1"; }
PASS=0
FAIL=0
check() {  # check "description" "shell test run inside the container"
  if X "$2" >/dev/null 2>&1; then PASS=$((PASS + 1)); echo "  ok   $1"
  else FAIL=$((FAIL + 1)); echo "  FAIL $1"; fi
}
wait_active() { for _ in 1 2 3 4 5 6 7 8 9 10; do X "systemctl is-active --quiet $1" && return 0; sleep 1; done; return 1; }

echo "== fresh OpenWebRX+ container"
./run.sh >/dev/null
for _ in $(seq 1 30); do X "systemctl is-active --quiet openwebrx" 2>/dev/null && break; sleep 1; done
echo "== 1. install.sh"
tar -C "$REPO" --exclude=./lab --exclude=./.git --exclude=__pycache__ -cf - . \
  | docker exec -i "$C" sh -c "rm -rf /root/new && mkdir /root/new && tar -xf - -C /root/new"
X "cd /root/new && ./install.sh" | sed 's/^/     /'
check "OpenWebRX+ package files intact (dpkg --verify)" "test -z \"\$(dpkg --verify openwebrx)\""
check "owrx-spider active" "systemctl is-active --quiet owrx-spider"
check "runs as the openwebrx account" "ps -eo user:32=,args= | grep -q '^openwebrx .*[-]m spiderd'"
check "default configuration created" "test -f /var/lib/owrx-spider/config.json"
check "config.json is private" "test \"\$(stat -c %a /var/lib/owrx-spider/config.json)\" = 600"
check "init.js loads the plugin exactly once" "test \"\$(grep -c \"Plugins.load(.spider.)\" /usr/lib/python3/dist-packages/htdocs/plugins/receiver/init.js)\" = 1"
check "plugin served by OpenWebRX+" "curl -sf http://127.0.0.1:8073/static/plugins/receiver/spider/spider.js | grep -q '_version = 1.0'"
check "OpenWebRX+ admin login works on spiderd" "curl -sf -H X-Spider-Admin:1 -d '{\"user\":\"admin\",\"password\":\"native-lab-pass\"}' http://127.0.0.1:7374/admin/api/login | grep -q ok"
check "settings saved through the admin API" "curl -s -c /tmp/ck -H X-Spider-Admin:1 -d '{\"user\":\"admin\",\"password\":\"native-lab-pass\"}' http://127.0.0.1:7374/admin/api/login >/dev/null && curl -sf -b /tmp/ck -H X-Spider-Admin:1 -d '{\"telnet\":{\"host\":\"dxc.example.org\",\"callsign\":\"EA4TEST\"}}' http://127.0.0.1:7374/admin/api/config | grep -q EA4TEST"
check "wrong password refused" "curl -s -H X-Spider-Admin:1 -d '{\"user\":\"admin\",\"password\":\"x\"}' http://127.0.0.1:7374/admin/api/login | grep -q Wrong"

echo "== 2. lifecycle tied to openwebrx.service"
X "systemctl stop openwebrx"; sleep 2
check "stop openwebrx -> owrx-spider stops" "! systemctl is-active --quiet owrx-spider"
X "systemctl start openwebrx"; wait_active owrx-spider || true
check "start openwebrx -> owrx-spider starts" "systemctl is-active --quiet owrx-spider"
PID1=$(X "systemctl show -p MainPID --value owrx-spider")
X "systemctl restart openwebrx"; sleep 1; wait_active owrx-spider || true
PID2=$(X "systemctl show -p MainPID --value owrx-spider")
if [ "$PID1" != "$PID2" ] && [ "$PID2" != 0 ]; then PASS=$((PASS + 1)); echo "  ok   restart openwebrx -> owrx-spider restarted"
else FAIL=$((FAIL + 1)); echo "  FAIL restart openwebrx -> owrx-spider restarted ($PID1 -> $PID2)"; fi
docker restart "$C" >/dev/null
for _ in $(seq 1 30); do X "systemctl is-active --quiet openwebrx" 2>/dev/null && break; sleep 1; done
wait_active owrx-spider || true
check "after a reboot both are running" "systemctl is-active --quiet openwebrx && systemctl is-active --quiet owrx-spider"

echo "== 3. update (install.sh again), uninstall, purge"
X "cd /root/new && ./install.sh >/dev/null"
check "update keeps the configuration" "grep -q EA4TEST /var/lib/owrx-spider/config.json"
check "update does not duplicate the init.js line" "test \"\$(grep -c \"Plugins.load(.spider.)\" /usr/lib/python3/dist-packages/htdocs/plugins/receiver/init.js)\" = 1"
X "cd /root/new && ./uninstall.sh" | sed 's/^/     /'
check "service gone" "! systemctl cat owrx-spider >/dev/null 2>&1 && ! pgrep -f '[-]m spiderd'"
check "plugin and init.js line gone" "test ! -e /usr/lib/python3/dist-packages/htdocs/plugins/receiver/spider && ! grep -qs spider /usr/lib/python3/dist-packages/htdocs/plugins/receiver/init.js"
check "openwebrx still fine" "systemctl is-active --quiet openwebrx && test -z \"\$(dpkg --verify openwebrx)\""
check "configuration kept without --purge" "test -f /var/lib/owrx-spider/config.json"
X "cd /root/new && ./uninstall.sh --purge >/dev/null"
check "--purge deletes the configuration" "test ! -e /var/lib/owrx-spider"

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
