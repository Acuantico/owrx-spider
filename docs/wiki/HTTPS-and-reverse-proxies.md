# HTTPS and reverse proxies

By default, the receiver page connects to spiderd at:

```
ws://<same host as the receiver>:7374/spots
```

When OpenWebRX+ is opened over plain `http://` with port 7374 reachable, this
works without any change.

When OpenWebRX+ is opened over **`https://`**, browsers only allow secure
WebSockets (`wss://`). Use one of these two options.

## Option 1: publish spiderd through your reverse proxy (recommended)

Add a location to the proxy that already serves OpenWebRX+. Example for nginx:

```nginx
location /spider/ {
    proxy_pass http://127.0.0.1:7374/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 1h;
}
```

Then tell the plugin where spiderd is. In
`htdocs/plugins/receiver/init.js`, add this line **before**
`Plugins.load('spider');`:

```js
window.spider_config = { url: 'wss://sdr.example.org/spider/spots' };
```

The configuration page is then available at
`https://sdr.example.org/spider/admin/`.

With this option you do not need to open port 7374 to the internet. You can
also restrict spiderd to the local machine: set `"bind": "127.0.0.1"` in the
`server` section of `config.json`, then restart spiderd.

## Option 2: give spiderd a certificate

Edit `config.json` (see [[Configuration]]) and set the certificate files in
the `server` section:

```json
"server": {
  "bind": "0.0.0.0",
  "port": 7374,
  "tls_cert": "/etc/letsencrypt/live/sdr.example.org/fullchain.pem",
  "tls_key": "/etc/letsencrypt/live/sdr.example.org/privkey.pem"
}
```

Then restart spiderd:

- package installs: `sudo systemctl restart owrx-spider`;
- Docker: restart the container.

The service account must be able to read both files.

With a certificate set:

- receiver pages opened over `https://` connect to `wss://<same host>:7374/spots`
  automatically;
- the configuration page is at `https://<host>:7374/admin/`.

The certificate must be valid for the host name used in the browser.

## Other ports or hosts

To use a different address or port without a proxy, set it in `init.js`
before the plugin is loaded:

```js
window.spider_config = { url: 'ws://192.168.1.20:7400/spots' };
// or only a different port on the receiver's own host:
window.spider_config = { port: 7400 };
```
