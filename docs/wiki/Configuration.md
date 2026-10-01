# Configuration

Everything is configured from spiderd's own web page. OpenWebRX+'s settings
pages are not changed.

## Opening the configuration page

Go to:

```
http://<receiver-address>:7374/admin/
```

Log in with an **OpenWebRX+ administrator account** of that installation: the
same user name and password you use for the OpenWebRX+ settings.

- spiderd reads the OpenWebRX+ accounts file on every login, and never
  changes it.
- Adding, removing or changing an account in OpenWebRX+ takes effect
  immediately.
- There are no separate Spider passwords.
- After 5 wrong passwords from the same address, logins from that address
  are blocked for one minute.

If the page shows a message instead of letting you log in, see
[[Troubleshooting]].

## The page

### Status

The status box at the top shows:

- the connection state: `disabled`, `connecting`, `connected` or `error`, with
  details;
- the number of spots received;
- the time of the last spot;
- how many receiver pages are connected right now.

### Cluster connection

**Enabled.** The master switch:

- On: spiderd connects to the cluster and receivers show the spots.
- Off: no connection is made, and the receiver plugin hides itself.

The cluster fields are empty on a new installation. Fill them in for the
cluster you want to use, then tick **Enabled**.

**Source.** Choose one of:

#### Telnet DX cluster

| Field | Description |
| --- | --- |
| Host | Name or IP address of the cluster node, e.g. `dxc.example.org` |
| Port | Telnet port of the node (often 7300, 7373, 8000 or 23) |
| Callsign | Your callsign. Most nodes require a valid one to log in |
| Password | Only if the node asks for one; leave empty otherwise |

spiderd answers the node's login prompt with the callsign, and with the
password if the node asks for one. It then reads the `DX de …` lines.

If the node rejects the callsign or password, the status shows the node's
message and spiderd waits one minute before trying again.

#### MQTT broker

| Field | Description |
| --- | --- |
| Broker URL | `mqtt://host:1883`, `mqtts://host:8883`, `ws://host/path` or `wss://host/path` |
| Topics | One per line. The MQTT wildcards `+` and `#` are allowed |
| User name / Password | Only if the broker requires them |
| Client ID | Leave empty to use a random one. Some brokers require a specific ID |
| QoS | 0 is enough for spots. 1 and 2 are supported |

The broker must publish spots as JSON or as `DX de …` text lines. See
[[MQTT message format|MQTT-message-format]].

### Waterfall display

| Field | Description |
| --- | --- |
| Spot lifetime (minutes) | How long a spot stays on the waterfall (1 – 120). Spots fade out during this time and disappear at the end |
| Show these spots | Which kinds are drawn: CW, Digital, Phone |

Click **Save**. Errors are listed above the button. When the settings are
saved:

- they apply at once, with no restart;
- receiver pages that are already open update by themselves;
- after a change of cluster, those pages start from an empty spot list.

Passwords are never sent back to the browser: the page shows `••••••••`
instead. Leave that placeholder unchanged to keep the stored password.

### Latest spots and service log

These sections show the last 25 spots received and the most recent messages
from spiderd. They are useful to check a new cluster setup.

## What receiver visitors see

When the cluster connection is enabled, the receiver's **Settings** section
shows a **Show DX cluster spots** checkbox. Each visitor can hide or show the
spots; the choice is remembered in their browser. Visitors cannot see or
change anything else.

## The settings file

The settings are saved in `config.json`. It is readable only by the service
account, because it can contain cluster or broker passwords. Its location is:

- package installs: `/var/lib/owrx-spider/config.json`;
- Docker: `/var/lib/openwebrx/spider/config.json`.

The `server` section of that file can only be changed by editing the file
(restart spiderd afterwards). It holds:

- `bind`: listening address;
- `port`: listening port;
- `tls_cert` / `tls_key`: see [[HTTPS and reverse proxies|HTTPS-and-reverse-proxies]].

If you change the port, receivers also need the new address. Set it in
`init.js` as explained in [[HTTPS and reverse proxies|HTTPS-and-reverse-proxies]].
