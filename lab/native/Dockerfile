# Clean package-based OpenWebRX+ (Debian 12) with systemd as PID 1, used to
# test install.sh / uninstall.sh and the start/stop coupling with openwebrx.
FROM debian:bookworm
ENV container=docker DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends systemd systemd-sysv curl gnupg ca-certificates procps python3 \
 && curl -s https://luarvique.github.io/ppa/openwebrx-plus.gpg | gpg --yes --dearmor -o /etc/apt/trusted.gpg.d/openwebrx-plus.gpg \
 && echo "deb [signed-by=/etc/apt/trusted.gpg.d/openwebrx-plus.gpg] https://luarvique.github.io/ppa/bookworm ./" > /etc/apt/sources.list.d/openwebrx-plus.list \
 && apt-get update \
 && apt-get install -y openwebrx \
 && rm -rf /var/lib/apt/lists/*
# Admin account, as the package's debconf question would create it.
RUN OWRX_PASSWORD=native-lab-pass openwebrx admin --noninteractive adduser admin
# The container's private cgroup tree is mounted read-only by Docker; make it
# writable for systemd (needs CAP_SYS_ADMIN, see run.sh; no --privileged).
STOPSIGNAL SIGRTMIN+3
CMD ["/bin/sh", "-c", "mount -o remount,rw /sys/fs/cgroup && exec /sbin/init"]
