#!/bin/sh
# Build and start the systemd-based lab (ports: OWRX 18274, spiderd 17474).
set -eu
cd "$(dirname "$0")"
docker build -q -t owrx-spider-native-lab .
docker rm -f owrx-spider-native >/dev/null 2>&1 || true
docker run -d --name owrx-spider-native --cgroupns=private --cap-add SYS_ADMIN --security-opt apparmor=unconfined \
  --tmpfs /run --tmpfs /run/lock --tmpfs /tmp \
  -p 127.0.0.1:18274:8073 -p 127.0.0.1:17474:7374 owrx-spider-native-lab
