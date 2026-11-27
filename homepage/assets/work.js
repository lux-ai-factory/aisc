// What the work pages (index.html's My tasks, work.html, rules.html, sign.html) share: making an element with
// its text, a time as the pages say it, a line that says what happened, and the address of a part's routes.
// Everything they show comes from the platform's answer; nothing here decides who may do what.
(function () {
  var enc = encodeURIComponent;

  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  // "2026-11-27 10:40 UTC": an ISO time in UTC, to the minute
  function when(iso) {
    if (!iso) return '';
    try { return new Date(iso).toISOString().slice(0, 16).replace('T', ' ') + ' UTC'; } catch (e) { return ''; }
  }

  function say(node, text, isError) {
    node.textContent = text || '';
    node.className = 'msg' + (isError ? ' err' : '');
  }

  function button(text, ghost) {
    var b = el('button', text, 'b' + (ghost ? ' ghost' : ''));
    b.type = 'button';
    return b;
  }

  function taskPath(project, kind, subject) {
    return '/api/projects/' + enc(project) + '/work/' + enc(kind) + '/' + enc(subject);
  }

  function partPath(project, kind, subject, part) {
    return taskPath(project, kind, subject) + '/parts/' + enc(part);
  }

  function signPage(project, kind, subject) {
    return '/sign.html?project=' + enc(project) + '&kind=' + enc(kind) + '&subject=' + enc(subject);
  }

  var STATES = {open: 'open', in_check: 'in check', done: 'done'};

  window.aiscWork = {el: el, when: when, say: say, button: button, taskPath: taskPath, partPath: partPath,
                     signPage: signPage, state: function (s) { return STATES[s] || s; }};
})();
