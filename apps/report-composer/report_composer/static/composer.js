// The report composer's one script. No logic of its own: it reads the page's data-* attributes,
// collects the form values, calls the API and draws what Python answered. Validity, coverage,
// labels and every decision stay in Python.
"use strict";
(function () {
  const main = document.querySelector("main[data-api]");
  if (!main) return;
  const api = main.dataset.api;
  const PICK_ONE = "Pick at least one, or choose All.";
  const EMPTY_CHAPTER = "This chapter is empty.";

  async function call(method, path, body, base) {
    let r;
    try {
      r = await fetch((base || api) + path, {
        method: method, credentials: "same-origin",
        headers: body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {                                   // no answer at all (network down): an error like others
      return { ok: false, status: 0, data: null };
    }
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    return { ok: r.ok, status: r.status, data: data };
  }

  function errorText(res) {
    const err = res.data && res.data.error;
    if (!err) return res.status === 0 ? "The composer could not be reached." : "Error " + res.status;
    const ref = (err.details || []).map(function (d) { return d && d.error_ref; }).filter(Boolean)[0];
    return err.message + (ref && err.message.indexOf(ref) < 0 ? " (ref " + ref + ")" : "");
  }

  // The message region at the top of every page (no browser alert)
  const region = main.querySelector("[data-message]");
  function say(text, ok) {
    if (!region) return;
    region.querySelector("[data-message-text]").textContent = text;
    region.classList.toggle("ok", !!ok);
    region.hidden = !text;
  }
  if (region) region.querySelector('[data-control="close-message"]').addEventListener("click", function () { say(""); });

  // The one confirmation dialog: its texts come from the button that asks (data-confirm-text)
  const dialog = main.querySelector("dialog[data-confirm]");
  function ask(text, action) {
    return new Promise(function (resolve) {
      if (!dialog || !dialog.showModal) { resolve(false); return; }
      dialog.querySelector("[data-confirm-message]").textContent = text;
      const ok = dialog.querySelector("[data-confirm-ok]");
      const cancel = dialog.querySelector("[data-confirm-cancel]");
      ok.textContent = action || "Confirm";
      function done(answer) {
        ok.removeEventListener("click", yes); cancel.removeEventListener("click", no);
        dialog.removeEventListener("cancel", no);
        if (dialog.open) dialog.close();
        resolve(answer);
      }
      function yes() { done(true); }
      function no(ev) { if (ev) ev.preventDefault(); done(false); }
      ok.addEventListener("click", yes); cancel.addEventListener("click", no);
      dialog.addEventListener("cancel", no);   // Esc
      dialog.showModal();
      cancel.focus();
    });
  }
  function askFor(button) { return ask(button.dataset.confirmText, button.dataset.confirmAction); }

  function readFile(file, asText) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = reject;
      if (asText) reader.readAsText(file); else reader.readAsDataURL(file);
    });
  }
  async function readJson(file) {
    try { return JSON.parse(await readFile(file, true)); } catch (e) { return null; }
  }

  // The layouts list
  if (main.dataset.page === "layouts") {
    const base = main.dataset.base;
    const presetsApi = main.dataset.presetsApi;
    const presetForm = main.querySelector('[data-control="save-preset-form"]');
    main.addEventListener("submit", async function (ev) {
      const form = ev.target;
      const what = form.dataset.control;
      if (!what) return;
      ev.preventDefault();
      let res;
      if (what === "new-layout") {
        res = await call("POST", "/layouts", { name: form.name.value, system_id: form.system_id.value,
                                               template_id: form.template_id.value || null, preset: form.preset.value });
      } else if (what === "import-preset") {
        const doc = await readJson(form.file.files[0]);
        if (!doc) { say("This file is not a report preset."); return; }
        res = await call("POST", "/layouts", { system_id: form.system_id.value, preset_file: doc });
      } else if (what === "save-preset-form") {
        res = await call("POST", "/layouts/" + form.dataset.layout + "/preset",
                         { name: form.name.value, keep_text: form.keep_text.checked });
        if (res.ok) { location.reload(); return; }
      } else return;
      if (res.ok) location.href = base + "/layouts/" + res.data.id; else say(errorText(res));
    });
    main.addEventListener("click", async function (ev) {
      const button = ev.target.closest("button[data-control]");
      if (!button) return;
      const what = button.dataset.control;
      let res = null;
      if (what === "delete") {
        if (!(await askFor(button))) return;
        res = await call("DELETE", "/layouts/" + button.dataset.layout);
      } else if (what === "duplicate") {
        res = await call("POST", "/layouts/" + button.dataset.layout + "/duplicate", {});
      } else if (what === "save-preset" && presetForm) {
        presetForm.dataset.layout = button.dataset.layout;
        presetForm.hidden = false;
        presetForm.name.focus();
        return;
      } else if (what === "cancel-preset" && presetForm) {
        presetForm.hidden = true;
        return;
      } else if (what === "delete-preset") {
        if (!(await askFor(button))) return;
        res = await call("DELETE", "/" + button.dataset.preset, undefined, presetsApi);
      } else return;
      if (res.ok) location.reload(); else say(errorText(res));
    });
    return;
  }

  // The templates (a report's look)
  if (main.dataset.page === "templates") {
    async function lookOf(form) {
      const body = { name: form.name.value, font: form.font.value, font_size_pt: parseFloat(form.font_size_pt.value),
                     primary_color: form.primary_color.value, accent_color: form.accent_color.value,
                     header_text: form.header_text.value || null, footer_text: form.footer_text.value || null,
                     marking: form.marking.value, show_document_id: form.show_document_id.checked };
      const file = form.logo.files[0];
      if (file) {
        const url = await readFile(file, false);
        body.logo = { mime: file.type, data_base64: url.slice(url.indexOf(",") + 1) };
      } else if (form.drop_logo && form.drop_logo.checked) {
        body.logo = null;
      } else if (form.dataset.template) {
        body.keep_logo = true;
      }
      return body;
    }
    main.addEventListener("submit", async function (ev) {
      const form = ev.target;
      const what = form.dataset.control;
      if (!what) return;
      ev.preventDefault();
      let res;
      if (what === "new-template") res = await call("POST", "/templates", await lookOf(form));
      else if (what === "edit-template") res = await call("PUT", "/templates/" + form.dataset.template, await lookOf(form));
      else if (what === "import-template") {
        const doc = await readJson(form.file.files[0]);
        if (!doc) { say("This file is not a template."); return; }
        res = await call("POST", "/templates/import", doc);
      } else return;
      if (res.ok) location.reload(); else say(errorText(res));
    });
    main.addEventListener("click", async function (ev) {
      const button = ev.target.closest('[data-control="delete-template"]');
      if (!button || !(await askFor(button))) return;
      const res = await call("DELETE", "/templates/" + button.dataset.template);
      if (res.ok) location.reload(); else say(errorText(res));
    });
    return;
  }

  // The editor
  const list = document.getElementById("blocks");
  const state = main.querySelector("[data-state]");
  const layoutId = main.dataset.layout;
  const frame = main.querySelector("iframe");
  const label = main.querySelector("[data-preview-label]");
  const coverageMap = main.querySelector("details[data-coverage-map]");
  const control = function (name) { return main.querySelector('[data-control="' + name + '"]'); };
  let revision = parseInt(main.dataset.revision, 10);
  let unsaved = false;

  function setLabel(text, error) {
    if (!label) return;
    label.textContent = text;
    label.classList.toggle("error", !!error);
  }
  function showSaved() { setLabel(unsaved ? "Preview of unsaved changes" : "Preview of revision " + revision); }
  function dirty() {
    unsaved = true;
    if (state) state.textContent = "Unsaved changes";
    showSaved();
    schedule();
  }

  // Indentation and the empty-chapter hint for the current order, as Python computes them (R-V5.8, R-V5.9)
  async function redrawOutline() {
    const blocks = Array.from(list.children).map(function (li) {
      return { instance_id: li.dataset.instanceId, block_type: li.dataset.blockType };
    });
    const res = await call("POST", "/layouts/" + layoutId + "/outline", { blocks: blocks });
    if (!res.ok) return;
    res.data.outline.forEach(function (o) {
      const li = list.querySelector('[data-instance-id="' + o.instance_id + '"]');
      if (!li) return;
      li.dataset.depth = String(o.depth);
      let hint = li.querySelector("[data-empty-chapter]");
      if (o.empty_chapter && !hint) {
        hint = document.createElement("p");
        hint.className = "hint"; hint.setAttribute("data-empty-chapter", ""); hint.textContent = EMPTY_CHAPTER;
        li.insertBefore(hint, li.querySelector("details, [data-problems]"));
      } else if (!o.empty_chapter && hint) hint.remove();
    });
  }
  function moved() { dirty(); redrawOutline(); }

  function parse(value, isJson) {
    if (!isJson) return value;
    try { return JSON.parse(value); } catch (e) { return value; }
  }

  function valueOf(input) {
    const kind = input.dataset.kind;
    if (kind === "bool") return input.checked;
    if (kind === "int") return input.value === "" ? null : parseInt(input.value, 10);
    if (kind === "int-or-null") return input.value === "" ? null : parseInt(input.value, 10);
    if (kind === "json") {
      if (input.tagName === "SELECT") return input.value === "" ? null : parse(input.value, true);
      const useMap = input.querySelector('[data-control="use-coverage-map"]');
      return useMap && useMap.checked ? [] : parse(input.dataset.value, true);
    }
    if (kind === "all-or-list") {
      const all = input.querySelector('input[data-choice="all"]');
      if (all && all.checked) return "all";
      return Array.from(input.querySelectorAll('.choices input[type="checkbox"]:checked')).map(function (b) {
        return parse(b.value, b.hasAttribute("data-json"));
      });
    }
    if (kind === "list") {
      if (input.tagName === "FIELDSET") {
        return Array.from(input.querySelectorAll('input[type="checkbox"]:checked')).map(function (b) { return b.value; });
      }
      return input.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    }
    return input.value;
  }

  function optionsOf(li) {
    const options = {};
    li.querySelectorAll("[data-option]").forEach(function (input) {
      if (input.closest("[data-field][hidden]")) return;          // hidden fields are not sent (R-V4.15)
      const v = valueOf(input);
      if (v === null && input.dataset.kind === "int-or-null") options[input.dataset.option] = null;
      else if (v !== null && v !== "") options[input.dataset.option] = v;
    });
    return options;
  }

  function collect() {
    return Array.from(list.children).map(function (li) {
      return { instance_id: li.dataset.instanceId, block_type: li.dataset.blockType, options: optionsOf(li) };
    });
  }

  // The coverage map: the ticked boxes, one entry per objective (Python computed the grid)
  function coverage() {
    if (!coverageMap) return undefined;
    const byObjective = {};
    const order = [];
    coverageMap.querySelectorAll("input[data-objective]:checked").forEach(function (box) {
      const id = box.dataset.objective;
      if (!byObjective[id]) { byObjective[id] = { objective_id: id, tests: [], checklists: [] }; order.push(id); }
      byObjective[id][box.dataset.kind].push(box.dataset.value);
    });
    return order.map(function (id) { return byObjective[id]; });
  }

  function editorState() {
    const pick = function (name) { const c = control(name); return c ? c.value : undefined; };
    const numbering = control("numbering");
    return { system_id: pick("version"), template_id: pick("template") || null, language: pick("language"),
             toc: pick("toc"), numbering: numbering ? numbering.checked : undefined, coverage: coverage(),
             blocks: collect() };
  }

  function pickOneHints() {
    list.querySelectorAll('fieldset[data-kind="all-or-list"]').forEach(function (set) {
      let hint = set.querySelector("[data-pick-one]");
      const empty = Array.isArray(valueOf(set)) && valueOf(set).length === 0;
      if (empty && !hint) {
        hint = document.createElement("p");
        hint.className = "inline-problem"; hint.setAttribute("data-pick-one", ""); hint.textContent = PICK_ONE;
        set.appendChild(hint);
      } else if (!empty && hint) hint.remove();
    });
  }

  function showProblems(problems) {
    list.querySelectorAll("[data-problems]").forEach(function (p) { p.textContent = ""; });
    const mapBox = main.querySelector("[data-map-problems]");
    if (mapBox) mapBox.textContent = "";
    const loose = [];
    (problems || []).forEach(function (p) {
      const text = (p.pointer ? p.pointer + ": " : "") + p.message + " ";
      const li = p.instance_id && list.querySelector('[data-instance-id="' + p.instance_id + '"]');
      const target = li ? li.querySelector("[data-problems]") : null;
      if (target) target.textContent += text;
      else if (mapBox && (p.pointer || "").indexOf("/coverage") === 0) mapBox.textContent += text;
      else loose.push(text);
    });
    say(loose.join(" "));
  }

  // show-if: a field is shown only while the option it names has one of the listed values
  function applyShowIf(scope) {
    scope.querySelectorAll("[data-show-if]").forEach(function (field) {
      const li = field.closest("li");
      let rule = {};
      try { rule = JSON.parse(field.getAttribute("data-show-if")); } catch (e) { rule = {}; }
      field.hidden = !Object.keys(rule).every(function (name) {
        const input = li.querySelector('[data-option="' + name + '"]');
        return input && rule[name].indexOf(valueOf(input)) >= 0;
      });
    });
  }

  // The preview of unsaved changes: 1.5 s after the last change, one request in flight, one queued
  let timer = null, inFlight = false, queued = false, sent = 0, shown = 0;
  let auto = true;
  try { auto = localStorage.getItem("composer.autoRefresh") !== "off"; } catch (e) { auto = true; }
  const autoBox = control("auto-refresh");
  if (autoBox) autoBox.checked = auto;

  function schedule() {
    if (!auto || !frame) return;
    clearTimeout(timer);
    timer = setTimeout(refresh, 1500);
  }
  async function refresh() {
    if (!frame || !control("save")) return;
    if (inFlight) { queued = true; return; }
    inFlight = true;
    const mine = ++sent;
    let res;
    try { res = await call("POST", "/layouts/" + layoutId + "/preview", editorState()); }
    finally { inFlight = false; }                        // a failure never blocks later previews
    if (mine > shown) {                                  // an answer to an older state is ignored
      shown = mine;
      if (res.ok) { frame.srcdoc = res.data.html; showSaved(); showProblems(res.data.problems); }
      else setLabel("The preview could not be made: " + errorText(res), true);
    }
    if (queued) { queued = false; refresh(); }
  }

  async function save(resetInvalid) {
    const body = Object.assign({ name: document.querySelector("h1").textContent.trim(), revision: revision },
                               editorState());
    if (resetInvalid) body.reset_invalid = true;
    const res = await call("PUT", "/layouts/" + layoutId, body);
    if (res.ok) {
      revision = res.data.revision;
      unsaved = false;
      showProblems([]);
      if (state) state.textContent = "Saved (revision " + revision + ")";
      showSaved();
      if (resetInvalid) location.reload(); else if (frame) frame.src = frame.src.split("?")[0] + "?r=" + revision;
      return true;
    }
    const err = res.data && res.data.error;
    if (err && err.code === "invalid_reference" && !resetInvalid &&
        await ask("Some options or coverage map entries name data this version does not have. Reset them and save?",
                  "Reset and save")) {
      return save(true);
    }
    showProblems(err && err.details && err.details.length ? err.details : [{ message: errorText(res) }]);
    return false;
  }

  main.addEventListener("click", async function (ev) {
    const target = ev.target.closest("[data-control], [data-add]");
    if (!target) return;
    const li = target.closest("li[data-instance-id]");
    const what = target.dataset.control;
    if (target.dataset.add) {
      const template = main.querySelector('template[data-block-template="' + target.dataset.add + '"]');
      const item = template.content.firstElementChild.cloneNode(true);
      item.dataset.instanceId = crypto.randomUUID();
      item.querySelectorAll('input[type="radio"]').forEach(function (r) {
        r.name = r.name.replace("__new__", item.dataset.instanceId);
      });
      list.appendChild(item);
      applyShowIf(item);
      moved();
    } else if (what === "move-up" && li && li.previousElementSibling) {
      list.insertBefore(li, li.previousElementSibling); moved();
    } else if (what === "move-down" && li && li.nextElementSibling) {
      list.insertBefore(li.nextElementSibling, li); moved();
    } else if (what === "remove" && li) {
      li.remove(); moved();
    } else if (what === "save") {
      await save(false);
    } else if (what === "refresh-preview") {
      clearTimeout(timer); refresh();
    } else if (what === "generate" || what === "generate-docx") {
      // the answer goes next to the button, and a finished document downloads at once
      const fmt = what === "generate-docx" ? "docx" : "pdf";
      const name = fmt === "docx" ? "Word document" : "PDF";
      const tell = function (text) { if (state) state.textContent = text; };
      if (unsaved) { tell("Save first: only a saved layout is generated."); return; }
      target.disabled = true;
      tell("Generating the " + name + "...");
      const res = await call("POST", "/layouts/" + layoutId + "/reports", { format: fmt });
      target.disabled = false;
      if (!res.ok) { tell(errorText(res)); return; }
      const failed = res.data.block_statuses.filter(function (s) { return s.status === "error"; });
      if (res.data.status === "failed") { tell("The " + name + " could not be made."); return; }
      const file = api + "/reports/" + res.data.id + "/download";
      tell(failed.length ? name + " ready, " + failed.length + " section(s) with errors: downloading."
                         : name + " ready: downloading.");
      const link = document.createElement("a");
      link.href = file; link.download = ""; document.body.appendChild(link); link.click(); link.remove();
      const reportsList = main.querySelector("[data-reports]");
      if (reportsList) {
        const item = document.createElement("li");
        const a = document.createElement("a");
        a.href = file; a.textContent = "Download";
        item.textContent = "Just now, revision " + revision + ", " + fmt.toUpperCase() + ", " + res.data.status + ": ";
        item.appendChild(a);
        const empty = reportsList.querySelector(".muted");
        if (empty) empty.remove();
        reportsList.prepend(item);
      }
    }
  });

  main.addEventListener("change", function (ev) {
    if (ev.target === autoBox) {
      auto = autoBox.checked;
      try { localStorage.setItem("composer.autoRefresh", auto ? "on" : "off"); } catch (e) { /* no storage */ }
      if (auto) schedule();
      return;
    }
    const li = ev.target.closest("li");
    if (li) { applyShowIf(li); pickOneHints(); }
    if (ev.target.closest("#blocks, .toolbar, details[data-coverage-map]")) dirty();
  });
  main.addEventListener("input", function (ev) {
    const filter = ev.target.closest("[data-filter]");
    if (filter) {
      const needle = filter.value.toLowerCase();
      filter.parentElement.querySelectorAll(".choices label").forEach(function (l) {
        l.hidden = needle && l.textContent.toLowerCase().indexOf(needle) < 0;
      });
      return;
    }
    if (ev.target.closest("#blocks")) dirty();
  });
  window.addEventListener("beforeunload", function (ev) {
    if (unsaved) { ev.preventDefault(); ev.returnValue = ""; }
  });

  // drag and drop (HTML5)
  let dragged = null;
  list.addEventListener("dragstart", function (ev) {
    dragged = ev.target.closest("li");
    if (dragged) dragged.classList.add("dragging");
  });
  list.addEventListener("dragend", function () {
    if (dragged) { dragged.classList.remove("dragging"); redrawOutline(); }
    dragged = null;
  });
  list.addEventListener("dragover", function (ev) {
    ev.preventDefault();
    const over = ev.target.closest("li");
    if (!dragged || !over || over === dragged) return;
    const box = over.getBoundingClientRect();
    list.insertBefore(dragged, ev.clientY < box.top + box.height / 2 ? over : over.nextSibling);
    dirty();
  });
})();
