'use strict';

(function () {
  var $ = function (id) { return document.getElementById(id); };
  var form = $('settings');
  var statusTimer = null;
  var dirty = false;

  function api(method, path, body) {
    var opts = { method: method, credentials: 'same-origin', headers: { 'X-Spider-Admin': '1' } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (res.status === 401 && path !== 'api/login') showLogin();
        return { ok: res.ok, status: res.status, data: data };
      });
    });
  }

  // -- login ---------------------------------------------------------------

  function showLogin(session) {
    stopStatus();
    $('app').hidden = true;
    $('who').hidden = true;
    $('login-card').hidden = false;
    var hint = $('login-hint');
    if (session && session.accounts === 'unreadable') {
      hint.textContent = 'spiderd cannot read the OpenWebRX+ accounts file (' + session.users_file +
        '). It must run as the same system user as OpenWebRX+.';
      hint.className = 'error';
    } else if (session && session.accounts === 'empty') {
      hint.textContent = 'OpenWebRX+ has no administrator account yet. Create one on the server with: ' +
        'sudo openwebrx admin adduser <name>';
      hint.className = 'error';
    }
    $('login-form').elements.user.focus();
  }

  $('login-form').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var f = ev.target;
    $('login-error').hidden = true;
    api('POST', 'api/login', { user: f.elements.user.value, password: f.elements.password.value })
      .then(function (r) {
        if (!r.ok) {
          $('login-error').textContent = r.data.error || 'Login failed';
          $('login-error').hidden = false;
          return;
        }
        f.elements.password.value = '';
        start();
      });
  });

  $('logout').addEventListener('click', function () {
    api('POST', 'api/logout', {}).then(function () { showLogin(); });
  });

  // -- settings form -------------------------------------------------------

  function field(name) { return form.elements[name]; }

  function fill(cfg) {
    field('enabled').checked = !!cfg.enabled;
    form.querySelectorAll('input[name="source"]').forEach(function (r) { r.checked = r.value === cfg.source; });
    ['host', 'port', 'callsign', 'password'].forEach(function (k) { field('telnet.' + k).value = cfg.telnet[k]; });
    ['url', 'username', 'password', 'client_id'].forEach(function (k) { field('mqtt.' + k).value = cfg.mqtt[k]; });
    field('mqtt.topics').value = cfg.mqtt.topics.join('\n');
    field('mqtt.qos').value = String(cfg.mqtt.qos);
    field('display.minutes').value = Math.round(cfg.display.max_age_sec / 60);
    form.querySelectorAll('input[name="group"]').forEach(function (c) {
      c.checked = cfg.display.groups.indexOf(c.value) >= 0;
    });
    showSourceFields();
    dirty = false;
  }

  function collect() {
    var source = form.querySelector('input[name="source"]:checked');
    var groups = [];
    form.querySelectorAll('input[name="group"]:checked').forEach(function (c) { groups.push(c.value); });
    return {
      enabled: field('enabled').checked,
      source: source ? source.value : 'mqtt',
      telnet: {
        host: field('telnet.host').value.trim(),
        port: parseInt(field('telnet.port').value, 10),
        callsign: field('telnet.callsign').value.trim(),
        password: field('telnet.password').value
      },
      mqtt: {
        url: field('mqtt.url').value.trim(),
        topics: field('mqtt.topics').value.split(/[\n,]/).map(function (t) { return t.trim(); }).filter(Boolean),
        username: field('mqtt.username').value,
        password: field('mqtt.password').value,
        client_id: field('mqtt.client_id').value.trim(),
        qos: parseInt(field('mqtt.qos').value, 10)
      },
      display: {
        max_age_sec: Math.round(parseFloat(field('display.minutes').value) * 60),
        groups: groups
      }
    };
  }

  function showSourceFields() {
    var source = form.querySelector('input[name="source"]:checked');
    form.querySelectorAll('.group[data-source]').forEach(function (g) {
      g.hidden = !source || g.getAttribute('data-source') !== source.value;
    });
  }

  form.addEventListener('change', function (ev) {
    dirty = true;
    $('saved').hidden = true;
    if (ev.target.name === 'source') showSourceFields();
  });
  form.addEventListener('input', function () { dirty = true; $('saved').hidden = true; });

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var button = form.querySelector('button[type="submit"]');
    var errors = $('form-errors');
    button.disabled = true;
    errors.hidden = true;
    api('POST', 'api/config', collect()).then(function (r) {
      button.disabled = false;
      if (!r.ok) {
        errors.textContent = '';
        (r.data.errors || [r.data.error || 'Could not save']).forEach(function (msg) {
          var li = document.createElement('li');
          li.textContent = msg;
          errors.appendChild(li);
        });
        errors.hidden = false;
        return;
      }
      fill(r.data);
      $('saved').hidden = false;
      refreshStatus();
    });
  });

  // -- status ----------------------------------------------------------------

  function ago(ts) {
    if (!ts) return '–';
    var s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60) return s + ' s ago';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    return Math.floor(s / 3600) + ' h ago';
  }

  function utc(ts) {
    var d = new Date(ts * 1000);
    return ('0' + d.getUTCHours()).slice(-2) + ('0' + d.getUTCMinutes()).slice(-2) + 'Z';
  }

  function cell(tr, text, cls) {
    var td = document.createElement('td');
    td.textContent = text;
    if (cls) td.className = cls;
    tr.appendChild(td);
  }

  function renderStatus(s) {
    var c = s.connection;
    var badge = $('st-badge');
    badge.textContent = c.state;
    badge.className = 'badge ' + c.state;
    $('st-detail').textContent = c.detail || (c.state === 'disabled' ? 'Cluster connection is turned off' : '');
    $('st-source').textContent = s.source === 'telnet' ? 'Telnet' : 'MQTT';
    $('st-spots').textContent = c.spots;
    $('st-last').textContent = ago(c.last_spot);
    $('st-browsers').textContent = s.browsers;
    $('version').textContent = 'spiderd ' + s.version + ' · up ' + Math.floor(s.uptime / 60) + ' min';

    var tbody = $('spots');
    tbody.textContent = '';
    s.recent.forEach(function (spot) {
      var tr = document.createElement('tr');
      tr.className = spot.group;
      cell(tr, utc(spot.time));
      cell(tr, (spot.freq / 1000).toFixed(1));
      cell(tr, spot.call, 'call');
      cell(tr, spot.mode || spot.group.toLowerCase());
      cell(tr, spot.spotter);
      cell(tr, spot.comment, 'comment');
      tbody.appendChild(tr);
    });

    $('log').textContent = s.log.map(function (l) {
      return new Date(l.time * 1000).toISOString().substr(11, 8) + ' ' + l.level + ' ' + l.message;
    }).join('\n');
  }

  function refreshStatus() {
    api('GET', 'api/status').then(function (r) { if (r.ok) renderStatus(r.data); });
  }

  function stopStatus() {
    if (statusTimer) clearInterval(statusTimer);
    statusTimer = null;
  }

  // -- start -----------------------------------------------------------------

  function start() {
    api('GET', 'api/config').then(function (r) {
      if (!r.ok) return;
      $('login-card').hidden = true;
      $('app').hidden = false;
      fill(r.data);
      refreshStatus();
      stopStatus();
      statusTimer = setInterval(refreshStatus, 3000);
      api('GET', 'api/session').then(function (s) {
        $('who-name').textContent = s.data.user || '';
        $('who').hidden = false;
      });
    });
  }

  window.addEventListener('beforeunload', function (ev) {
    if (dirty) { ev.preventDefault(); ev.returnValue = ''; }
  });

  api('GET', 'api/session').then(function (r) {
    if (r.data.user) start(); else showLogin(r.data);
  });
})();
