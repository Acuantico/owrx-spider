# Installation with Docker

This page is for the `slechev/openwebrxplus` image (and `-softmbe`). There is
no installer: you mount the plugin, spiderd and its service definition into
the container. spiderd then runs inside the OpenWebRX+ container, under the
image's own service supervisor (s6). It starts after OpenWebRX+ and stops with
the container.

## 1. Download the repository

Put it next to your `docker-compose.yml`:

```sh
git clone https://github.com/Acuantico/owrx-spider.git
```

## 2. Create `init.js`

Create `init.js` next to `docker-compose.yml`, with at least:

```js
Plugins.load('spider');
```

If you already mount your own `init.js` for other plugins, add that line to it
instead.

## 3. Add the port and volumes

```yaml
services:
  openwebrx:
    image: slechev/openwebrxplus
    ports:
      - "8073:8073"
      - "7374:7374"   # spiderd: spots and configuration page
    volumes:
      - ./etc:/etc/openwebrx
      - ./var:/var/lib/openwebrx
      # owrx-spider
      - ./owrx-spider/plugin/spider:/usr/lib/python3/dist-packages/htdocs/plugins/receiver/spider:ro
      - ./init.js:/usr/lib/python3/dist-packages/htdocs/plugins/receiver/init.js:ro
      - ./owrx-spider/spiderd:/opt/owrx-spider/spiderd:ro
      - ./owrx-spider/packaging/s6/owrx-spider:/etc/s6-overlay/s6-rc.d/owrx-spider:ro
      - ./owrx-spider/packaging/s6/user-contents.d-owrx-spider:/etc/s6-overlay/s6-rc.d/user/contents.d/owrx-spider:ro
```

Keep your existing `etc` and `var` volumes as they are. spiderd stores its
settings in `/var/lib/openwebrx/spider/`, inside the `var` volume, so they
survive container updates.

## 4. Recreate the container

```sh
docker compose up -d
```

Check that spiderd started:

```sh
docker logs openwebrx 2>&1 | grep -E "owrx-spider|spiderd"
```

You should see `service owrx-spider successfully started` and
`spiderd … listening on http://0.0.0.0:7374`.

Continue with [[Configuration]].

## Notes

- Use your container's name in the `docker logs` command.
- The login uses the OpenWebRX+ administrator accounts of the container. These
  are the ones created with `OPENWEBRX_ADMIN_USER` / `OPENWEBRX_ADMIN_PASSWORD`,
  or with `docker exec -it <container> openwebrx admin adduser <name>`.
- To update Spider, run `git pull` in `owrx-spider`, then
  `docker compose restart`.
