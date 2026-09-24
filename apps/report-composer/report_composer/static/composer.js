// The report composer's one script (report run 2026-09-23, R4.1.1). No logic of its own: it reads
// the page's data-* attributes, collects the form values and calls the API; Python decides the rest.
"use strict";
(function () {
  const main = document.querySelector("main[data-api]");
  if (!main) return;
  const api = main.dataset.api;

  async function call(method, path, body) {
    const r = await fetch(api + path, {
      method: method, credentials: "same-origin",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    return { ok: r.ok, status: r.status, data: data };
  }

  function message(res) {
    return (res.data && res.data.error && res.data.error.message) || ("Error " + res.status);
  }

  // ── the layouts list ──
  if (main.dataset.page === "layouts") {
    const base = main.dataset.base;
    const create = main.querySelector('[data-control="new-layout"]');
    if (create) create.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const res = await call("POST", "/layouts", { name: create.name.value, system_id: create.system_id.value,
                                                    template_id: create.template_id.value });
      if (res.ok) location.href = base + "/layouts/" + res.data.id; else alert(message(res));
    });
    main.addEventListener("click", async function (ev) {
      const button = ev.target.closest('[data-control="delete"]');
      if (!button || !confirm("Delete this layout and its generated reports?")) return;
      const res = await call("DELETE", "/layouts/" + button.dataset.layout);
      if (res.ok) location.reload(); else alert(message(res));
    });
    return;
  }

  // ── the templates (a report's look) ──
  if (main.dataset.page === "templates") {
    function readFile(file, asText) {
      return new Promise(function (resolve, reject) {
        const reader = new FileReader();
        reader.onload = function () { resolve(reader.result); };
        reader.onerror = reject;
        if (asText) reader.readAsText(file); else reader.readAsDataURL(file);
      });
    }
    async function lookOf(form) {
      const body = { name: form.name.value, font: form.font.value, font_size_pt: parseFloat(form.font_size_pt.value),
                     primary_color: form.primary_color.value, accent_color: form.accent_color.value };
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
        let doc;
        try { doc = JSON.parse(await readFile(form.file.files[0], true)); } catch (e) { alert("This file is not a template."); return; }
        res = await call("POST", "/templates/import", doc);
      } else return;
      if (res.ok) location.reload(); else alert(message(res));
    });
    main.addEventListener("click", async function (ev) {
      const button = ev.target.closest('[data-control="delete-template"]');
      if (!button || !confirm("Delete this template? Layouts using it must choose another before their next save.")) return;
      const res = await call("DELETE", "/templates/" + button.dataset.template);
      if (res.ok) location.reload(); else alert(message(res));
    });
    return;
  }

  // ── the editor ──
  const list = document.getElementById("blocks");
  const state = main.querySelector("[data-state]");
  const layoutId = main.dataset.layout;
  let revision = parseInt(main.dataset.revision, 10);

  let unsaved = false;
  function dirty() { unsaved = true; if (state) state.textContent = "Unsaved changes"; }

  function valueOf(input) {
    const kind = input.dataset.kind;
    if (kind === "bool") return input.checked;
    if (kind === "int") return input.value === "" ? null : parseInt(input.value, 10);
    if (kind === "all-or-list") {
      const picked = Array.from(input.selectedOptions).map(function (o) { return o.value; });
      return picked.length ? picked : "all";
    }
    if (kind === "list") {
      if (input.tagName === "SELECT") return Array.from(input.selectedOptions).map(function (o) { return o.value; });
      return input.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    }
    if (kind === "links") {
      return input.value.split("\n").map(function (line) { return line.trim(); }).filter(Boolean).map(function (line) {
        const head = line.split(":");
        const rest = head.slice(1).join(":").split("|");
        const items = function (s) { return (s || "").split(",").map(function (x) { return x.trim(); }).filter(Boolean); };
        return { objective_id: head[0].trim(), tests: items(rest[0]), checklists: items(rest[1]) };
      });
    }
    return input.value;
  }

  function collect() {
    return Array.from(list.children).map(function (li) {
      const options = {};
      li.querySelectorAll("[data-option]").forEach(function (input) {
        const v = valueOf(input);
        if (v !== null && v !== "") options[input.dataset.option] = v;
      });
      return { instance_id: li.dataset.instanceId, block_type: li.dataset.blockType, options: options };
    });
  }

  function showProblems(problems) {
    list.querySelectorAll("[data-problems]").forEach(function (p) { p.textContent = ""; });
    (problems || []).forEach(function (p) {
      const li = p.instance_id && list.querySelector('[data-instance-id="' + p.instance_id + '"]');
      const target = li ? li.querySelector("[data-problems]") : null;
      const text = (p.pointer ? p.pointer + ": " : "") + p.message;
      if (target) target.textContent += text + " "; else alert(text);
    });
  }

  function reloadPreview() {
    const frame = main.querySelector("iframe");
    if (frame) frame.src = frame.src.split("?")[0] + "?r=" + revision;
  }

  async function save(resetInvalid) {
    const version = main.querySelector('[data-control="version"]');
    const title = document.querySelector("h1");
    const template = main.querySelector('[data-control="template"]');
    const body = { name: title.textContent.trim(), revision: revision, blocks: collect(),
                   system_id: version ? version.value : undefined, template_id: template ? template.value || null : null };
    if (resetInvalid) body.reset_invalid = true;
    const res = await call("PUT", "/layouts/" + layoutId, body);
    if (res.ok) {
      revision = res.data.revision;
      unsaved = false;
      showProblems([]);
      if (state) state.textContent = "Saved (revision " + revision + ")";
      reloadPreview();
      return true;
    }
    const err = res.data && res.data.error;
    if (err && err.code === "invalid_reference" && !resetInvalid &&
        confirm("Some options name data of another version. Reset them to their defaults?")) {
      return save(true);
    }
    showProblems(err && err.details && err.details.length ? err.details : [{ message: message(res) }]);
    return false;
  }

  main.addEventListener("click", async function (ev) {
    const control = ev.target.closest("[data-control], [data-add]");
    if (!control) return;
    const li = control.closest("li[data-instance-id]");
    const what = control.dataset.control;
    if (control.dataset.add) {
      const template = main.querySelector('template[data-block-template="' + control.dataset.add + '"]');
      const item = template.content.firstElementChild.cloneNode(true);
      item.dataset.instanceId = crypto.randomUUID();
      list.appendChild(item);
      dirty();
    } else if (what === "move-up" && li && li.previousElementSibling) {
      list.insertBefore(li, li.previousElementSibling); dirty();
    } else if (what === "move-down" && li && li.nextElementSibling) {
      list.insertBefore(li.nextElementSibling, li); dirty();
    } else if (what === "remove" && li) {
      li.remove(); dirty();
    } else if (what === "save") {
      await save(false);
    } else if (what === "generate") {
      // the answer goes next to the button, and a finished PDF downloads at once
      const say = function (text) { if (state) state.textContent = text; };
      if (unsaved) { say("Save first: only a saved layout is generated."); return; }
      control.disabled = true;
      say("Generating the PDF...");
      const res = await call("POST", "/layouts/" + layoutId + "/reports", {});
      control.disabled = false;
      if (!res.ok) { say(message(res)); return; }
      const failed = res.data.block_statuses.filter(function (s) { return s.status === "error"; });
      if (res.data.status === "failed") { say("The PDF could not be made."); return; }
      const pdf = api + "/reports/" + res.data.id + "/pdf";
      say(failed.length ? "PDF ready, " + failed.length + " section(s) with errors: downloading." : "PDF ready: downloading.");
      const link = document.createElement("a");
      link.href = pdf; link.download = ""; document.body.appendChild(link); link.click(); link.remove();
      const reportsList = main.querySelector("[data-reports]");
      if (reportsList) {
        const item = document.createElement("li");
        item.innerHTML = "Just now, revision " + revision + ", " + res.data.status + ': <a href="' + pdf + '">Download</a>';
        const empty = reportsList.querySelector(".muted");
        if (empty) empty.remove();
        reportsList.prepend(item);
      }
    }
  });

  main.addEventListener("change", function (ev) { if (ev.target.closest("#blocks, .toolbar")) dirty(); });
  main.addEventListener("input", function (ev) { if (ev.target.closest("#blocks")) dirty(); });

  // drag and drop (HTML5)
  let dragged = null;
  list.addEventListener("dragstart", function (ev) {
    dragged = ev.target.closest("li");
    if (dragged) dragged.classList.add("dragging");
  });
  list.addEventListener("dragend", function () {
    if (dragged) dragged.classList.remove("dragging");
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
