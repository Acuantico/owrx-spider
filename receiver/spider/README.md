# Spider DX Cluster overlay plugin

This plugin overlays DX Cluster spots on the OpenWebRX+ waterfall. It connects to a local WebSocket bridge (spiderd) which consumes a DX cluster telnet feed and broadcasts normalized JSON spots.

## Configuration

Global defaults can be set in `htdocs/init.js` (or any loaded script) via:

```js
window.spider_config_global = {
  ws_url: "ws://localhost:7373/spots",
  max_age_sec: 300,
  modes: ["CW","SSB","FT8"],
  enabled: true
};
```

Per-user overrides can be stored in localStorage under `spider_config` as JSON:

```js
localStorage.setItem('spider_config', JSON.stringify({
  max_age_sec: 180,
  modes: ["CW","FT8"],
  enabled: true
}));
```

## Notes

- The overlay is rendered on a separate canvas layered above the waterfall.
- The plugin logs errors to the console but never interrupts the UI.
- Spots fade out automatically after `max_age_sec`.
- Use the Spider toggle in the receiver panel to show/hide cluster overlays.
