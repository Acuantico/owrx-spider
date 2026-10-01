/*
 * spider: DX cluster spots on the OpenWebRX+ waterfall.
 *
 * Receiver plugin for the official OpenWebRX+ plugin loader. The spots come
 * from the spiderd service (same host, port 7374 by default), which is also
 * where the cluster connection is configured.
 *
 * Load it from htdocs/plugins/receiver/init.js:
 *
 *   Plugins.load('spider');
 *
 * Optional, before loading, when spiderd is reached through another URL
 * (for example a reverse proxy on an HTTPS receiver):
 *
 *   window.spider_config = { url: 'wss://sdr.example.org/spider/spots' };
 */

Plugins.spider._version = 1.0;

Plugins.spider.init = function () {
  var DEFAULT_PORT = 7374;
  var COLORS = { CW: '#7dfffd', DIGITAL: '#ff2bd6', PHONE: '#ffe600' };
  var STORE_KEY = 'spider_show';
  var MAX_SPOTS = 1500;

  var userCfg = (typeof window.spider_config === 'object' && window.spider_config) || {};

  var state = {
    server: null,          // public config pushed by spiderd
    show: loadShow(),      // visitor preference
    spots: [],
    ws: null,
    backoff: 1000,
    canvas: null,
    ctx: null,
    checkbox: null,
    lastKey: '',
    lastDraw: 0
  };

  function spotsUrl() {
    if (userCfg.url) return String(userCfg.url);
    var scheme = location.protocol === 'https:' ? 'wss://' : 'ws://';
    return scheme + location.hostname + ':' + (userCfg.port || DEFAULT_PORT) + '/spots';
  }

  function loadShow() {
    try {
      var v = localStorage.getItem(STORE_KEY);
      return v === null ? true : v === 'true';
    } catch (e) {
      return true;
    }
  }

  function saveShow(value) {
    try { localStorage.setItem(STORE_KEY, value ? 'true' : 'false'); } catch (e) { /* private mode */ }
  }

  function active() {
    return !!(state.server && state.server.enabled && state.show);
  }

  // -- settings checkbox ------------------------------------------------------

  function installToggle() {
    if (state.checkbox) return;
    var settings = document.querySelector('#openwebrx-section-settings');
    settings = settings && settings.nextElementSibling;
    if (!settings) return;

    var row = document.createElement('div');
    row.className = 'openwebrx-panel-line openwebrx-spider-line';
    row.innerHTML =
      '<label class="openwebrx-checkbox openwebrx-spider-setting" ' +
      'title="DX cluster spots on the waterfall. Colors: CW cyan, digital magenta, phone yellow.">' +
      '<input type="checkbox" id="openwebrx-spider-toggle">' +
      '<span>Show DX cluster spots</span></label>';
    settings.appendChild(row);

    state.checkbox = row.querySelector('input');
    state.checkbox.checked = state.show;
    state.checkbox.addEventListener('change', function () {
      state.show = this.checked;
      saveShow(state.show);
      redraw(true);
    });
  }

  function removeToggle() {
    var row = document.querySelector('.openwebrx-spider-line');
    if (row) row.parentNode.removeChild(row);
    state.checkbox = null;
  }

  // -- spot store -------------------------------------------------------------

  function addSpot(s) {
    if (!s || typeof s.freq !== 'number' || !s.call) return;
    var spot = {
      freq: s.freq,
      call: String(s.call),
      group: COLORS[s.group] ? s.group : 'PHONE',
      time: s.time || Math.floor(Date.now() / 1000)
    };
    // The same station spotted again near the same frequency replaces the old spot.
    for (var i = state.spots.length - 1; i >= 0; i--) {
      var o = state.spots[i];
      if (o.call === spot.call && Math.abs(o.freq - spot.freq) < 1000) {
        state.spots.splice(i, 1);
        break;
      }
    }
    state.spots.push(spot);
    if (state.spots.length > MAX_SPOTS) state.spots.splice(0, state.spots.length - MAX_SPOTS);
  }

  function prune(now) {
    var maxAge = state.server ? state.server.max_age_sec : 600;
    state.spots = state.spots.filter(function (s) { return now - s.time <= maxAge; });
  }

  // -- connection to spiderd --------------------------------------------------

  function connect() {
    var ws;
    try {
      ws = new WebSocket(spotsUrl());
    } catch (e) {
      console.error('spider: cannot open ' + spotsUrl(), e);
      return;
    }
    state.ws = ws;
    ws.onopen = function () { state.backoff = 1000; };
    ws.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === 'config') {
        applyServerConfig(msg.config);
      } else if (msg.type === 'spots') {
        if (msg.reset) state.spots = [];
        (msg.spots || []).forEach(addSpot);
        redraw(true);
      } else if (msg.type === 'spot') {
        addSpot(msg.spot);
        redraw(true);
      }
    };
    ws.onclose = function () {
      state.ws = null;
      setTimeout(connect, state.backoff);
      state.backoff = Math.min(30000, state.backoff * 2);
    };
  }

  function applyServerConfig(cfg) {
    state.server = cfg || null;
    if (state.server && state.server.enabled) {
      installToggle();
    } else {
      removeToggle();
      state.spots = [];
    }
    redraw(true);
  }

  // -- overlay ----------------------------------------------------------------

  function ensureCanvas() {
    if (state.canvas) return true;
    var container = document.getElementById('webrx-canvas-container');
    if (!container) return false;
    var canvas = document.createElement('canvas');
    canvas.className = 'openwebrx-spider-overlay';
    canvas.setAttribute('aria-hidden', 'true');
    container.appendChild(canvas);
    state.canvas = canvas;
    state.ctx = canvas.getContext('2d');
    return true;
  }

  // Area of the waterfall not covered by the receiver panels.
  function clipArea(w, h) {
    var rect = state.canvas.getBoundingClientRect();
    var clipW = w;
    var clipH = h;
    var right = document.getElementById('openwebrx-panels-container-right');
    if (right) {
      var overlap = right.getBoundingClientRect().left - rect.left;
      if (overlap > 0 && overlap < clipW) clipW = Math.floor(overlap);
    }
    var panels = document.querySelectorAll('.openwebrx-panel');
    for (var i = 0; i < panels.length; i++) {
      var r = panels[i].getBoundingClientRect();
      if (!r.width || !r.height || r.bottom <= rect.top || r.top >= rect.top + h) continue;
      if (r.right <= rect.left || r.left >= rect.left + clipW) continue;
      clipH = Math.min(clipH, Math.max(0, Math.floor(r.top - rect.top)));
    }
    return { w: clipW, h: clipH };
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function redraw(force) {
    if (!state.canvas || typeof get_visible_freq_range !== 'function') return;
    var range = get_visible_freq_range();
    var container = state.canvas.parentNode;
    var w = waterfallWidth();
    var h = container.clientHeight;
    var key = range ? [range.start, range.end, w, h, zoom_offset_px].join(':') : '';
    var now = Date.now();
    // Redraw when the view changed, when asked to, and once a second for fading.
    if (!force && key === state.lastKey && now - state.lastDraw < 1000) return;
    state.lastKey = key;
    state.lastDraw = now;

    var dpr = window.devicePixelRatio || 1;
    var canvas = state.canvas;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
    }
    // The container moves with the zoom; keep the overlay on screen.
    canvas.style.left = (-zoom_offset_px) + 'px';

    var ctx = state.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!active() || !range || !w || !h) return;

    var nowSec = Math.floor(now / 1000);
    prune(nowSec);
    var groups = state.server.groups || [];
    var maxAge = state.server.max_age_sec;
    var clip = clipArea(w, h);

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, clip.w, clip.h);
    ctx.clip();
    ctx.font = '11px "DejaVu Sans", Verdana, Geneva, sans-serif';
    ctx.textBaseline = 'top';

    // Each spot is a label chip starting at its frequency (no marker lines),
    // stacked in lanes so neighbours do not overlap.
    var LANES = 9, LANE_STEP = 16, TOP = 4, CHIP_H = 14, GAP = 6;
    var lanes = [];
    var spots = state.spots.slice().sort(function (a, b) {
      return a.freq - b.freq || b.time - a.time;  // stable order: less jumping
    });

    for (var i = 0; i < spots.length; i++) {
      var spot = spots[i];
      if (groups.indexOf(spot.group) < 0) continue;
      if (spot.freq < range.start || spot.freq > range.end) continue;
      var x = scale_px_from_freq(spot.freq, range);
      if (x < -2 || x > clip.w + 2) continue;

      var label = spot.call.length > 12 ? spot.call.slice(0, 11) + '\u2026' : spot.call;
      var chipW = Math.ceil(ctx.measureText(label).width) + 18;
      var chipX = Math.max(2, Math.min(w - chipW - 2, x));
      if (chipX + chipW > clip.w) continue;

      var lane = -1;
      for (var l = 0; l < LANES && lane < 0; l++) {
        lanes[l] = lanes[l] || [];
        var free = true;
        for (var k = 0; k < lanes[l].length; k++) {
          var r = lanes[l][k];
          if (chipX < r[1] + GAP && chipX + chipW + GAP > r[0]) { free = false; break; }
        }
        if (free) { lane = l; lanes[l].push([chipX, chipX + chipW]); }
      }
      if (lane < 0) continue;
      var y = TOP + lane * LANE_STEP;
      if (y + CHIP_H > clip.h - 2) continue;

      var alpha = Math.max(0, 1 - (nowSec - spot.time) / maxAge);
      var color = COLORS[spot.group];

      ctx.globalAlpha = Math.min(1, 0.9 * alpha + 0.1);
      ctx.fillStyle = 'rgba(10, 12, 16, 0.92)';
      roundRect(ctx, chipX - 1, y - 1, chipW + 2, CHIP_H + 2, 5);
      ctx.fill();
      ctx.fillStyle = color;                       // mode accent stripe
      roundRect(ctx, chipX - 1, y - 1, 4, CHIP_H + 2, 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(180, 190, 210, 0.28)';
      ctx.lineWidth = 1;
      roundRect(ctx, chipX - 1, y - 1, chipW + 2, CHIP_H + 2, 5);
      ctx.stroke();
      ctx.fillStyle = color;                       // mode dot
      ctx.beginPath();
      ctx.arc(chipX + 8, y + CHIP_H / 2, 2.1, 0, Math.PI * 2);
      ctx.fill();

      ctx.globalAlpha = Math.min(1, 0.95 * alpha + 0.05);
      ctx.fillStyle = '#EAF2FF';
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.35)';
      ctx.lineWidth = 2;
      ctx.strokeText(label, chipX + 13, y + 1);
      ctx.fillText(label, chipX + 13, y + 1);
    }
    ctx.restore();
  }

  function frame() {
    redraw(false);
    window.requestAnimationFrame(frame);
  }

  // -- start ------------------------------------------------------------------

  function start() {
    if (!ensureCanvas()) {
      console.error('spider: waterfall container not found');
      return;
    }
    connect();
    window.requestAnimationFrame(frame);
  }

  // Same readiness test as the utils plugin's "event:owrx_initialized".
  (function waitForReceiver() {
    if (typeof clock !== 'undefined' && typeof get_visible_freq_range === 'function') start();
    else setTimeout(waitForReceiver, 100);
  })();

  return true;
};
