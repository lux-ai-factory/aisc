// Whether the AI Assessment Sandbox card can open: only once the AI system, or one of its AI card components, is
// connected (an endpoint) or has an uploaded file tests can reach. `answer` is aisc.call's answer to
// GET /api/projects/{slug}/targets; an answer that says nothing (refused, not answering, no list) never locks the
// card. Gives {open: true}, or {open: false, system: <the system's name>} for the sentence under the card.
window.aiscSandboxGate = function (answer, projectName) {
  var targets = answer && answer.ok && answer.data && answer.data.targets;
  if (!Array.isArray(targets)) return {open: true};
  var connected = targets.some(function (t) { return !!(t && (t.endpoint || t.file)); });
  if (connected) return {open: true};
  var system = targets.filter(function (t) { return t && t.kind === 'system' && t.label; })[0];
  return {open: false, system: system ? system.label : projectName};
};

// Each installed test's Configure and Run (the buttons of the Run tests column's tiles in `box`) wait like Run tests
// above them: while nothing is connected (`open` false) they are greyed out, have no link and say why; once
// `open`, they get back their link and title. Locking twice keeps the link to give back.
window.aiscLockTestTiles = function (box, open) {
  var WHY = 'Connect at least one component of the AI system first';
  [].forEach.call(box.querySelectorAll('.tile'), function (tile) {
    if (open) tile.classList.remove('is-off'); else tile.classList.add('is-off');
    [].forEach.call(tile.querySelectorAll('a.tile-btn'), function (a) {
      if (open) {
        if (a.hasAttribute('data-open-href')) {
          a.setAttribute('href', a.getAttribute('data-open-href'));
          a.removeAttribute('data-open-href');
        }
        if (a.hasAttribute('data-open-title')) {
          a.setAttribute('title', a.getAttribute('data-open-title'));
          a.removeAttribute('data-open-title');
        }
        a.classList.remove('off');
        a.removeAttribute('aria-disabled');
        return;
      }
      if (a.hasAttribute('href')) {
        a.setAttribute('data-open-href', a.getAttribute('href'));
        a.removeAttribute('href');
      }
      if (!a.hasAttribute('data-open-title')) a.setAttribute('data-open-title', a.getAttribute('title') || '');
      a.setAttribute('title', WHY);
      a.classList.add('off');
      a.setAttribute('aria-disabled', 'true');
    });
  });
};
