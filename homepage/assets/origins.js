// Where this install's engine, Keycloak and dashboard are. The gateway serves them from the install's
// settings (API_URL_EXTERNAL, KEYCLOAK_URL_EXTERNAL, DASHBOARD_EXTERNAL_URL) at /origins.json. Until it
// answers, or when it cannot, they are this host's defaults: the engine on the default port, Keycloak
// on 8081, the dashboard on 8188.
//
// A link marked data-origin="engine" data-path="/flower/" gets its href from here, now and again when
// the gateway answers. aiscLink(el, name, path) marks a link the page builds later; aiscOrigin(name) is
// the address as known now; aiscOriginsReady settles once the gateway has answered or failed.
(function () {
  var host = location.protocol + '//' + location.hostname;
  var origins = { engine: host, keycloak: host + ':8081', dashboard: host + ':8188' };

  // an http(s) address, without a trailing slash; anything else is not taken
  function clean(value) {
    var v = String(value || '').replace(/\/+$/, '');
    return /^https?:\/\/[^\/?#\s"'<>]+(\/[^?#\s"'<>]*)?$/.test(v) ? v : '';
  }

  function apply() {
    var links = document.querySelectorAll('[data-origin]');
    for (var i = 0; i < links.length; i++) {
      var el = links[i];
      var base = origins[el.dataset.origin];
      if (base) el.href = base + (el.dataset.path || '');
    }
  }

  window.aiscOrigin = function (name) { return origins[name]; };
  window.aiscLink = function (el, name, path) {
    el.dataset.origin = name;
    el.dataset.path = path || '';
    el.href = origins[name] + (path || '');
  };
  apply();
  window.aiscOriginsReady = fetch('/origins.json', { credentials: 'same-origin' })
    .then(function (r) { return r.ok ? r.json() : {}; })
    .catch(function () { return {}; })
    .then(function (answer) {
      Object.keys(origins).forEach(function (name) {
        var v = clean(answer && answer[name]);
        if (v) origins[name] = v;
      });
      apply();
    });
})();
