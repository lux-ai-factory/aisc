// The browser beacon (ledger spec 3.5): what only the page knows, such as a page opened or left with
// unsaved changes. Best effort: sendBeacon with text/plain needs no CORS preflight, and the gateway
// witnesses the request itself, so who sent it is certain; what it says is the browser's word.
(function () {
  window.aiscBeacon = function (project, action, details) {
    try {
      var body = new Blob([JSON.stringify({project: project, action: action, details: details || {}})],
                          {type: 'text/plain;charset=UTF-8'});
      if (navigator.sendBeacon) navigator.sendBeacon('/api/ledger/beacon', body);
    } catch (e) { /* never break the page for a beacon */ }
  };
})();
