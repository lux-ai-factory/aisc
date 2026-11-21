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
