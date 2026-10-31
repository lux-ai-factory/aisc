// What every launcher page needs to talk to the platform: which project it is about, and one way to call
// the platform and read its answer. What a page does with the answer stays in the page.
//
// aisc.project() is the project's handle from /p/<slug> or ?project=<slug>, or null when the address names
// none or names something that is not a handle (a malformed escape too: it never throws).
// aisc.call(path, {method, body}) calls with the person's sign-in and always settles, never rejects, on
// {ok, status, data, message}: data is the JSON answer or null (empty, or not JSON, as Caddy's 502 while
// the platform is down); message is null when ok, else the platform's own words (FastAPI's detail, a
// sentence or a list of field errors) or 'Refused (HTTP n)'. Status 0 is nothing answering.
(function () {
  // the platform's rule for a handle (platform_service/projects.py, _SLUG_RE and SLUG_MAX)
  var HANDLE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  var HANDLE_MAX = 64;
  var NOT_ANSWERING = 'The platform is not answering.';

  function project() {
    try {
      var inPath = /^\/p\/([^\/]+)\/?$/.exec(location.pathname);
      var raw = inPath ? decodeURIComponent(inPath[1]) : new URLSearchParams(location.search).get('project');
      return raw && raw.length <= HANDLE_MAX && HANDLE.test(raw) ? raw : null;
    } catch (e) {
      return null;
    }
  }

  function message(status, data) {
    var detail = data && data.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map(function (e) { return e && e.msg ? e.msg : String(e); }).join('; ');
    }
    return 'Refused (HTTP ' + status + ')';
  }

  function parsed(text) {
    try { return text ? JSON.parse(text) : null; } catch (e) { return null; }
  }

  function call(path, opts) {
    opts = opts || {};
    var init = {method: opts.method || 'GET', credentials: 'same-origin', headers: {}};
    if (opts.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }
    return fetch(path, init).then(function (res) {
      return res.text().catch(function () { return ''; }).then(function (text) {
        var data = parsed(text);
        return {ok: res.ok, status: res.status, data: data, message: res.ok ? null : message(res.status, data)};
      });
    }, function () {
      return {ok: false, status: 0, data: null, message: NOT_ANSWERING};
    });
  }

  window.aisc = {project: project, call: call, NOT_ANSWERING: NOT_ANSWERING};
})();
