# Updating and uninstalling

## Updating (package installs)

```sh
cd owrx-spider
git pull
sudo ./install.sh
```

Your settings in `/var/lib/owrx-spider` are kept. The `init.js` line is not
added twice.

## Updating (Docker)

```sh
cd owrx-spider && git pull && cd ..
docker compose restart
```

## Uninstalling (package installs)

```sh
cd owrx-spider
sudo ./uninstall.sh            # keeps the settings
sudo ./uninstall.sh --purge    # also deletes the settings
```

This removes:

- the service;
- `/opt/owrx-spider`;
- the receiver plugin.

About `init.js`:

- If the installer created it and you never edited it, it is deleted.
- Otherwise, only the `Plugins.load('spider');` line is removed.

OpenWebRX+ itself is not touched.

## Uninstalling (Docker)

Remove the `7374` port and the five `owrx-spider` volumes from
`docker-compose.yml`. Remove the `Plugins.load('spider');` line from your
`init.js`. Then run `docker compose up -d`.

To delete the settings as well, delete `var/spider/` in your data volume.
