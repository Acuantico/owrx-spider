#!/bin/sh
# Fresh state for the laboratory (wipes lab/runtime only).
set -eu
cd "$(dirname "$0")"
rm -rf runtime
mkdir -p runtime/etc runtime/var
cp seed/settings.json runtime/var/settings.json
# Broker accounts: "spider" (subscriber used by spiderd) and "publisher".
mkdir -p runtime/mosquitto
docker run --rm -v "$(pwd)/runtime/mosquitto:/out" eclipse-mosquitto:2 sh -c \
  'mosquitto_passwd -b -c /out/passwd spider spider-mqtt-pass &&
   mosquitto_passwd -b /out/passwd publisher publisher-pass && chmod 644 /out/passwd'
echo "Lab state prepared in $(pwd)/runtime. Start with: docker compose up -d"
