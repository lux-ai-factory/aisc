# Report composer: modules, layouts without data, reports that choose their data. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Layouts hold only structure (modules, order, template, index, numbering, coverage map); the
data (AI card version, test period, other versions, compare version) is chosen when a report is
generated; five read-only built-in layouts replace the presets.

**Architecture:** The composer (FastAPI + Jinja, one small script) stops storing a version on the
layout and sends the renderer a snapshot v3 with a `selection`. The renderer applies the selection in
its engine queries (period, anchor version or all versions), gains a `test_runs` block, and matches
dashboard comments to the version current when they were written. Screens follow the templates-screen
pattern: page actions in the header, one editor, destructive actions inside the editor. Generation is a
Python-rendered form page.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, psycopg 3, PostgreSQL (one database per project),
jsonschema, pytest, Playwright with the system Chrome; renderer uses uv.

**Spec:** `docs/superpowers/specs/2026-09-28-report-modules-design.md` (approved 2026-09-28, with the
planning corrections of commit `6df2a4a`). Read it before any task.

## Global Constraints

- Test first for every change (write the failing test, see it fail for the right reason, then code).
- Nothing is pushed. `master` of every repo stays untouched. Commits are local.
- Repos and branches: superproject `~/aisc-definitive` branch `definitive/2026-09-27` (contains
  `apps/report-composer`, `homepage/`, `scripts/`); submodule `~/aisc-definitive/apps/qualification`
  branch `definitive/2026-09-27`; renderer `~/aisc-report-generator` branch `dev`.
- Engine tables use Sean's names: `engine.aisc_backend_evaluation`, `aisc_backend_evaluationplugin`,
  `aisc_backend_pluginconfig`, `aisc_backend_plugin`, `aisc_backend_measurement`, ...
- No em dashes in prose, comments, UI text or commit messages.
- The composer's `static/composer.js` stays under 500 lines (`test_r4_1_1_one_small_script`) and holds
  no logic: decisions are made in Python.
- UI copy (verbatim from the spec): "This project has no AI card version yet. Save the AI card in
  qualification first." and "No test runs between <from> and <to> for version N."
- Secret configuration keys: any key whose name contains key, token, secret, password, passwd,
  credential or auth (any case) prints as "(hidden)", at every level.
- A period is two dates, both inclusive, in UTC: from 00:00 of the first to 00:00 of the day after the last.
- Composer tests: `cd ~/aisc-definitive/apps/report-composer && .venv/bin/python -m pytest -q -p no:cacheprovider <files>`
  (the full suite takes about 8 minutes; `test_e2e*.py` need a running renderer).
- Renderer tests: `cd ~/aisc-report-generator && env -u DATABASE_URL -u PLATFORM_TEST_DATABASE_URL AISC_INSTALL_DIR=$HOME/aisc-definitive uv run --extra dev pytest -q -p no:cacheprovider <files>`
- Known failure before this plan, not to be fixed here:
  `test_isolation_project_databases.py::test_i8_2_i1_7_the_project_tables_have_no_project_id_and_keys_on_project_system`.
  Task 5 changes the table it inspects: re-check whether its failure message changed, and report it.

## Review Focus

1. A period whose "to" date is the same day as a run: the run is included (the day is inclusive).
2. A plugin configuration holding `{"api_key": ...}` or a nested `{"auth": {"password": ...}}`: the value
   never reaches the HTML, in summary or full (the seed holds `CONFIGSECRET`).
3. A comment written after a newer version was saved: it belongs to the newer version and is not printed
   for the older one unless "other versions" is on.
4. An old preset file (format `aisc-report-preset` version 1, with `toc`, `language` and evaluation ids):
   it imports, with a notice for each dropped reference.
5. Generating from a layout in a project that has no version: a clear message, no 500.

Each is pinned by a test in the task that owns the code (Tasks 3, 4, 6, 9, 12).

---

### Task 1: One source again: bring today's `~/aisc-modes` work into `~/aisc-definitive`

The templates screen redesign, the projects page and the Framework menu were built in `~/aisc-modes`
and are uncommitted there. The base versions of every file are identical in both checkouts (checked
2026-09-28), so this is a copy.

**Files:**
- Copy from `~/aisc-modes` to `~/aisc-definitive` (same paths):
  - `apps/report-composer/report_composer/pages.py`
  - `apps/report-composer/report_composer/static/composer.css`
  - `apps/report-composer/report_composer/static/composer.js`
  - `apps/report-composer/report_composer/templates/templates.html.j2`
  - `apps/report-composer/tests/test_pages.py`
  - `apps/report-composer/tests/test_v2_templates.py`
  - `apps/report-composer/tests/test_templates_browser.py` (new)
  - `homepage/index.html`
  - `scripts/tests/test_projects_page_scale.py` (new)
- Already in `~/aisc-definitive/apps/qualification` (uncommitted): `src/components/NavMenu.tsx`,
  `src/components/SiteHeader.tsx`, `src/app/globals.css`, `test/unit/SiteHeader.test.tsx`.

- [ ] **Step 1: Check the bases are still identical** (another session may have committed since)

```bash
cd ~/aisc-definitive
for f in apps/report-composer/report_composer/pages.py apps/report-composer/report_composer/static/composer.css \
  apps/report-composer/report_composer/static/composer.js apps/report-composer/report_composer/templates/templates.html.j2 \
  apps/report-composer/tests/test_pages.py apps/report-composer/tests/test_v2_templates.py homepage/index.html; do
  a=$(git -C ~/aisc-modes show HEAD:$f | sha1sum); b=$(git show HEAD:$f | sha1sum); [ "$a" = "$b" ] || echo "DIFFERENT $f"; done
```
Expected: no output. If a file differs, stop and report it: merge by hand, do not overwrite.

- [ ] **Step 2: Copy the files**

```bash
cd ~/aisc-modes
for f in apps/report-composer/report_composer/pages.py apps/report-composer/report_composer/static/composer.css \
  apps/report-composer/report_composer/static/composer.js apps/report-composer/report_composer/templates/templates.html.j2 \
  apps/report-composer/tests/test_pages.py apps/report-composer/tests/test_v2_templates.py \
  apps/report-composer/tests/test_templates_browser.py homepage/index.html scripts/tests/test_projects_page_scale.py; do
  cp "$f" ~/aisc-definitive/"$f"; done
```

- [ ] **Step 3: Run the tests of what was copied**

```bash
cd ~/aisc-definitive/apps/report-composer && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_pages.py tests/test_v2_templates.py tests/test_templates_browser.py
cd ~/aisc-definitive && platform/.venv/bin/python -m pytest -q -p no:cacheprovider --noconftest scripts/tests/test_projects_page_scale.py scripts/tests/test_project_page_scale.py
cd ~/aisc-definitive/apps/qualification && npx vitest run test/unit/SiteHeader.test.tsx && npx tsc --noEmit
```
Expected: all pass (composer 38, homepage 13, qualification 6 + clean typecheck).

- [ ] **Step 4: Commit** (qualification in its own repo first, then the superproject with the gitlink)

```bash
cd ~/aisc-definitive/apps/qualification
git add src/components/NavMenu.tsx src/components/SiteHeader.tsx src/app/globals.css test/unit/SiteHeader.test.tsx
git commit -m "Header: Question sets, Questionnaires and Methodology in one Framework menu"
cd ~/aisc-definitive
git add apps/qualification apps/report-composer/report_composer/pages.py apps/report-composer/report_composer/static \
  apps/report-composer/report_composer/templates/templates.html.j2 apps/report-composer/tests/test_pages.py \
  apps/report-composer/tests/test_v2_templates.py apps/report-composer/tests/test_templates_browser.py \
  homepage/index.html scripts/tests/test_projects_page_scale.py
git commit -m "Templates screen: one editor; projects page bigger and centred; qualification gitlink (Framework menu)"
```
Only these paths: `git status` must show the other session's files (if any) still unstaged.

---

### Task 2: Renderer: a selection in the snapshot

**Files:**
- Create: `~/aisc-report-generator/report_renderer/selection.py`
- Modify: `report_renderer/snapshot.py` (SCHEMA, lines 15-69), `report_renderer/context.py` (`ReportInfo`,
  line 50), `report_renderer/document.py` (`render`, lines 219-245)
- Test: `tests/test_selection.py`

**Interfaces:**
- Produces: `Selection(period_from: datetime | None = None, period_to: datetime | None = None,
  other_versions: bool = False, compare_to: str | None = None)` (frozen dataclass),
  `EMPTY = Selection()`, `from_snapshot(d: dict | None) -> Selection`,
  `ReportInfo.selection: Selection` (default `EMPTY`), snapshot key `selection`
  `{period_from, period_to, other_versions, compare_to}` (ISO 8601 date-time strings or null),
  `snapshot_version` 3 accepted.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selection.py
"""The report's data selection (report modules spec 2026-09-28, sections 6 and 7.1)."""
from datetime import datetime, timezone

from conftest import need


def test_an_absent_selection_is_the_anchor_version_alone():
    sel = need("report_renderer.selection", "from_snapshot")(None)
    assert (sel.period_from, sel.period_to, sel.other_versions, sel.compare_to) == (None, None, False, None)


def test_a_selection_is_read_from_its_iso_strings():
    sel = need("report_renderer.selection", "from_snapshot")(
        {"period_from": "2026-09-10T00:00:00+00:00", "period_to": "2026-09-11T00:00:00+00:00",
         "other_versions": True, "compare_to": "a1000000-0000-4000-8000-000000000001"})
    assert sel.period_from == datetime(2026, 9, 10, tzinfo=timezone.utc)
    assert sel.period_to == datetime(2026, 9, 11, tzinfo=timezone.utc)
    assert sel.other_versions is True and sel.compare_to == "a1000000-0000-4000-8000-000000000001"


def test_the_snapshot_schema_takes_a_selection_and_version_3():
    validate = need("report_renderer.snapshot", "validate")
    from conftest import snapshot
    s = snapshot([], project="A", system="A_V2", mode="preview")
    s["snapshot_version"] = 3
    s["selection"] = {"period_from": None, "period_to": "2026-09-11T00:00:00+00:00", "other_versions": False,
                      "compare_to": None}
    assert validate(s) == []
    s["selection"]["colour"] = "red"
    assert validate(s) != []                       # nothing else in a selection


def test_the_fingerprint_changes_with_the_selection():
    fp = need("report_renderer.snapshot", "fingerprint")
    from conftest import snapshot
    a = snapshot([], project="A", system="A_V2", mode="pdf")
    b = {**a, "selection": {"period_from": "2026-09-10T00:00:00+00:00", "period_to": None,
                            "other_versions": False, "compare_to": None}}
    assert fp(a) != fp(b)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_selection.py` (with the env of Global Constraints)
Expected: FAIL, `report_renderer.selection` missing; schema test fails on `snapshot_version: 3`.

- [ ] **Step 3: Implement**

```python
# report_renderer/selection.py
"""The data a report covers, chosen when it is generated (report modules spec 2026-09-28, section 6).

The anchor version is the snapshot's `system_id`. The selection adds the period of test runs (from
inclusive, to exclusive, UTC), whether runs made against other versions are included, and the version
Changes since compares with. An absent selection is the anchor version alone, all its runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Selection:
    period_from: datetime | None = None
    period_to: datetime | None = None
    other_versions: bool = False
    compare_to: str | None = None


EMPTY = Selection()


def _when(value) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def from_snapshot(d: dict | None) -> Selection:
    if not d:
        return EMPTY
    return Selection(period_from=_when(d.get("period_from")), period_to=_when(d.get("period_to")),
                     other_versions=bool(d.get("other_versions", False)), compare_to=d.get("compare_to") or None)
```

In `snapshot.py` SCHEMA: change `"snapshot_version": {"type": "integer", "enum": [1, 2]}` to
`[1, 2, 3]`, and add after `"coverage_links"`:

```python
        # the data the report covers (report modules spec, section 6); absent: the anchor version alone
        "selection": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "period_from": {"type": ["string", "null"], "format": "date-time"},
                "period_to": {"type": ["string", "null"], "format": "date-time"},
                "other_versions": {"type": "boolean"},
                "compare_to": {"type": ["string", "null"], "pattern": UUID_PATTERN},
            },
        },
```

In `context.py` `ReportInfo`, add the last field `selection: Selection = EMPTY` (import from
`.selection`). In `document.render`, add to the `report` dict:
`"selection": selection.from_snapshot(snapshot.get("selection"))` (import `from . import selection`).
`fingerprint` already hashes every key but mode, requested_by and document, so it covers the selection.

- [ ] **Step 4: Run the tests**

Run: `... pytest -q -p no:cacheprovider tests/test_selection.py tests/test_snapshot*.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/aisc-report-generator && git add report_renderer/selection.py report_renderer/snapshot.py report_renderer/context.py report_renderer/document.py tests/test_selection.py
git commit -m "Snapshot v3: a data selection (period, other versions, compare version)"
```

---

### Task 3: Renderer: engine queries honour the selection

**Files:**
- Modify: `report_renderer/data/engine.py` (`_SCOPE`, `_params`, `evaluations`, `runs`, `inputs`,
  `observations`, `measurements`, `artifacts`), `report_renderer/views.py` (`evaluation_names`,
  `load_runs`, `EvaluationView`)
- Test: `tests/test_selection_runs.py`

**Interfaces:**
- Consumes: `Selection`, `ReportInfo.selection` (Task 2).
- Produces: every engine query takes a keyword `selection: Selection | None = None`; `None` behaves as
  today. `evaluations(...)` rows gain `version_number` (int or None). `EvaluationView.version_number`.
  `load_runs(ctx, ...)` reads `ctx.report.selection`.

- [ ] **Step 1: Write the failing tests** (project Alpha: V1 from 09-01, V2 from 09-08, V3 from 09-15;
  runs 11 V1 09-02, 23 V2 09-09, 21 V2 09-10, 22 V2 09-11 Failed, 41 and 42 no version 09-12, 31 V3 09-16)

```python
# tests/test_selection_runs.py
"""Runs in a period, of the anchor version or of all versions (report modules spec, 6 and 7.1)."""
import pytest

from conftest import IDS, need
from v2_block_helpers import one, v2_snapshot, render_snapshot, section, text, block

pytestmark = pytest.mark.db


def _sel(**over):
    return {"period_from": None, "period_to": None, "other_versions": False, "compare_to": None, **over}


def _results(deps, sel):
    b = block("test_results", detail="summary")
    snap = v2_snapshot([b], project="A", system="A_V2", snapshot_version=3, selection=sel)
    return text(section(render_snapshot(deps, snap)["html"], b["instance_id"]))


def test_without_a_selection_every_run_of_the_anchor_version(deps):
    t = _results(deps, _sel())
    assert "LangBiTe" in t and "Mystery" in t and "MLAReject" not in t     # V1's tool is not there


def test_the_last_day_of_the_period_is_included(deps):
    t = _results(deps, _sel(period_from="2026-09-10T00:00:00+00:00", period_to="2026-09-11T00:00:00+00:00"))
    assert "Mystery" in t                  # run 21 of 09-10 09:00, the one day of the period


def test_a_period_leaves_out_runs_outside_it(deps):
    t = _results(deps, _sel(period_from="2026-09-11T00:00:00+00:00", period_to="2026-09-12T00:00:00+00:00"))
    assert "Mystery" not in t              # only run 22 (09-11, LangBiTe, failed) is in the period


def test_other_versions_brings_their_runs_marked_with_their_version(deps):
    t = _results(deps, _sel(other_versions=True))
    assert "MLAReject" in t and "(version 1)" in t
    assert "(no version)" in t             # runs 41 and 42 have no version


def test_the_cover_says_when_other_versions_are_included(deps):
    b = block("cover")
    for on, expected in ((True, True), (False, False)):
        snap = v2_snapshot([b], project="A", system="A_V2", snapshot_version=3, selection=_sel(other_versions=on))
        t = text(section(render_snapshot(deps, snap)["html"], b["instance_id"]))
        assert ("Includes test runs made against other versions." in t) is expected
```

- [ ] **Step 2: Run them to see them fail**

Run: `... pytest -q -p no:cacheprovider tests/test_selection_runs.py`
Expected: the period tests FAIL (the period is ignored), the other-versions test FAILS.

- [ ] **Step 3: Implement**

In `data/engine.py`, replace the constant scope by a function and pass the selection through:

```python
_EVAL = "engine.aisc_backend_evaluation e"


def _scope(selection) -> str:
    """The runs a report covers: the anchor version's (or every version's) inside the period."""
    version = "TRUE" if (selection is not None and selection.other_versions) else "e.system_id = %(s)s"
    return (f"{version} AND (%(pf)s::timestamptz IS NULL OR e.created_at >= %(pf)s)"
            " AND (%(pt)s::timestamptz IS NULL OR e.created_at < %(pt)s)")


def _params(system_id, selection=None, **extra) -> dict:
    return {"s": check_uuid(system_id), "pf": getattr(selection, "period_from", None),
            "pt": getattr(selection, "period_to", None), **extra}
```

Every query that used `_SCOPE` uses `_scope(selection)` and `_params(system_id, selection, ...)`, and
takes `selection=None` as its last keyword. `evaluations` also returns the version:

```python
def evaluations(project_id, system_id, *, sources, statuses=None, pids=None, selection=None) -> list[dict]:
    return db.project_rows(sources, project_id, "engine",
        f"SELECT e.id, e.pid::text AS pid, e.status, e.created_at, s.number AS version_number"
        f" FROM {_EVAL} LEFT JOIN project.system s ON s.pid = e.system_id"
        f" WHERE {_scope(selection)} AND (%(st)s::text[] IS NULL OR e.status = ANY(%(st)s))"
        f" AND (%(pids)s::uuid[] IS NULL OR e.pid = ANY(%(pids)s)) ORDER BY e.created_at, e.id",
        _params(system_id, selection, st=statuses, pids=pids))
```

`unversioned_count` and `newest_newer_evaluation` keep their own filters (they describe the version).
In `views.py`: `EvaluationView` gains `version_number: int | None`; `load_runs` takes
`selection = getattr(ctx.report, "selection", None)` and passes `selection=selection` to every engine
call; `evaluation_names` appends " (version N)" when `version_number` differs from
`ctx.system["number"]`, and " (no version)" when it is None. In `blocks/cover.py`, `render` adds a
line "Includes test runs made against other versions." under the subtitle when
`ctx.report.selection.other_versions` is true. In `blocks/changes_since.py`, the base
context for the older version uses `report=dataclasses.replace(ctx.report, selection=EMPTY)` so an
older version's tests are read whole.

- [ ] **Step 4: Run the tests, then the whole renderer suite**

Run: `... pytest -q -p no:cacheprovider tests/test_selection_runs.py` then `... pytest -q -p no:cacheprovider`
Expected: PASS; the full suite as green as before this task (note any test that pinned the old
numbering or labels and fix it only if the new label is the spec's).

- [ ] **Step 5: Commit**

```bash
git add report_renderer/data/engine.py report_renderer/views.py report_renderer/blocks/changes_since.py report_renderer/blocks/cover.py tests/test_selection_runs.py
git commit -m "Engine queries: the report's period and the other-versions switch"
```

---

### Task 4: Renderer: the Test runs block, secrets hidden

**Files:**
- Create: `report_renderer/blocks/test_runs.py`, `report_renderer/redact.py`,
  `report_renderer/templates/blocks/test_runs.html` (follow the folder the other blocks' templates use:
  `ls report_renderer/templates` and copy the pattern of `test_results`)
- Modify: `report_renderer/blocks/__init__.py` (`BUILTIN_BLOCKS`, lines 16-18),
  `report_renderer/data/engine.py` (new `run_details`)
- Test: `tests/test_block_test_runs.py`, `tests/test_redact.py`

**Interfaces:**
- Consumes: `_scope`, `_params`, `Selection` (Tasks 2, 3).
- Produces: block type `test_runs`, title "Test runs", options `detail` ("summary" | "full", default
  "summary") and `configuration` ("none" | "summary" | "full", default "none");
  `engine.run_details(project_id, system_id, *, sources, evaluation_ids, selection=None) -> list[dict]`
  with keys `evaluation_id, name, display_name, status, started_at, finished_at, config_name, config`;
  `redact.redact(value) -> value`, `redact.summary(config: dict, limit: int = 8) -> list[tuple[str, str]]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_redact.py
from conftest import need


def test_secret_keys_are_hidden_at_every_level():
    redact = need("report_renderer.redact", "redact")
    out = redact({"api_key": "S1", "model": "gpt", "auth": {"password": "S2"}, "list": [{"Token": "S3"}]})
    assert out == {"api_key": "(hidden)", "model": "gpt", "auth": "(hidden)", "list": [{"Token": "(hidden)"}]}


def test_the_summary_is_the_top_level_scalars_redacted_and_bounded():
    summary = need("report_renderer.redact", "summary")
    cfg = {"api_key": "S1", "model": "gpt", "temperature": 0.2, "nested": {"a": 1}}
    assert summary(cfg) == [("api_key", "(hidden)"), ("model", "gpt"), ("temperature", "0.2")]
    assert len(summary({f"k{i}": i for i in range(20)})) == 8
```

```python
# tests/test_block_test_runs.py
"""Test runs (report modules spec, sections 3 and 4.1)."""
import pytest

from v2_block_helpers import one

pytestmark = pytest.mark.db


def test_summary_is_one_line_per_run_of_the_version(deps):
    t, st, node, _ = one(deps, "test_runs", project="A", system="A_V2")
    assert st["status"] == "ok"
    assert len(node.select("tbody tr")) == 3            # runs 21, 22, 23 of version 2
    assert "Failed" in t


def test_full_configuration_never_prints_a_secret(deps):
    t, _, _, result = one(deps, "test_runs", project="A", system="A_V2", detail="full", configuration="full")
    assert "CONFIGSECRET" not in result["html"]           # the seed's config {"api_key": "CONFIGSECRET"}
    assert "(hidden)" in t


def test_no_runs_in_the_period_says_so(deps):
    from conftest import IDS
    from v2_block_helpers import block, v2_snapshot, render_snapshot, section, text
    b = block("test_runs")
    snap = v2_snapshot([b], project="A", system="A_V2", snapshot_version=3,
                       selection={"period_from": "2026-01-01T00:00:00+00:00",
                                  "period_to": "2026-01-02T00:00:00+00:00", "other_versions": False,
                                  "compare_to": None})
    t = text(section(render_snapshot(deps, snap)["html"], b["instance_id"]))
    assert "No test runs between 2026-01-01 and 2026-01-01 for version 2." in t
```

- [ ] **Step 2: Run them to see them fail**

Expected: FAIL, module `report_renderer.redact` and block type `test_runs` missing.

- [ ] **Step 3: Implement**

```python
# report_renderer/redact.py
"""A tool's configuration may hold credentials (the engine stores them in plugin_config.config).
Every key whose name contains one of SECRET_WORDS prints as HIDDEN, at every level."""
from __future__ import annotations

SECRET_WORDS = ("key", "token", "secret", "password", "passwd", "credential", "auth")
HIDDEN = "(hidden)"


def _secret(name) -> bool:
    n = str(name).lower()
    return any(w in n for w in SECRET_WORDS)


def redact(value):
    if isinstance(value, dict):
        return {k: (HIDDEN if _secret(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def summary(config: dict, limit: int = 8) -> list[tuple[str, str]]:
    """The configuration's top-level scalar settings, redacted, at most `limit` of them."""
    out = []
    for k, v in redact(config or {}).items():
        if isinstance(v, (dict, list)):
            continue
        out.append((str(k), "" if v is None else str(v)))
        if len(out) == limit:
            break
    return out
```

`data/engine.py`:

```python
def run_details(project_id, system_id, *, sources, evaluation_ids, selection=None) -> list[dict]:
    """The tool runs of these evaluations with their times and configuration (the Test runs block).
    The configuration is returned whole: the block redacts it before printing (report_renderer.redact)."""
    return db.project_rows(sources, project_id, "engine",
        "SELECT ep.evaluation_id, ep.name, pl.display_name, ep.status, ep.started_at, ep.finished_at,"
        " pc.name AS config_name, pc.config"
        " FROM engine.aisc_backend_evaluationplugin ep JOIN " + _EVAL + " ON e.id = ep.evaluation_id"
        " LEFT JOIN engine.aisc_backend_pluginconfig pc ON pc.id = ep.plugin_config_id"
        " LEFT JOIN engine.aisc_backend_plugin pl ON pl.id = pc.plugin_id"
        f" WHERE {_scope(selection)} AND e.id = ANY(%(ids)s::bigint[]) ORDER BY ep.started_at, ep.id",
        _params(system_id, selection, ids=list(evaluation_ids)))
```

Update the module docstring's sentence about reading the plugin config only by id: it is now read
whole for Test runs and redacted there.

`blocks/test_runs.py`: a `BaseBlockRenderer` subclass with `type_id = "test_runs"`, `title = "Test runs"`,
`contract_version = 1`, `reads = ("engine", "platform")`, `description = "The test runs in the
report's period: when they ran, the tools and their configuration."`, options schema
`{"type": "object", "additionalProperties": False, "properties": {"detail": {"enum": ["summary",
"full"], "title": "Detail"}, "configuration": {"enum": ["none", "summary", "full"], "title":
"Configuration"}}}`, `default_options = {"detail": "summary", "configuration": "none"}`.
`load(ctx, options)`: `sel = getattr(ctx.report, "selection", None)`;
`evals = ctx.data.engine.evaluations(selection=sel)`; `details =
ctx.data.engine.run_details(evaluation_ids=[e["id"] for e in evals], selection=sel)` grouped by
`evaluation_id`. `render`: no evaluations: `empty_result(f"No test runs between {from} and {to} for
version {ctx.system['number']}.")` where from/to are the period's dates as `YYYY-MM-DD` (to printed as
`period_to - 1 day`; an open end prints "the start" or "today"); summary: one `<tr>` per evaluation
(date, version label as in Task 3, status, tool names); full: one section per evaluation, each tool with
start, end and status; configuration "summary": a `<dl>` of `redact.summary(config)`, "full": a
`<pre>` of `json.dumps(redact.redact(config), indent=2, sort_keys=True)` escaped by the template
engine. Register the class in `BUILTIN_BLOCKS`.

- [ ] **Step 4: Run the tests, then the whole suite**

Expected: PASS; `assert_no_foreign_data` style tests elsewhere still pass (no `CONFIGSECRET`).

- [ ] **Step 5: Commit**

```bash
git add report_renderer/redact.py report_renderer/blocks/test_runs.py report_renderer/blocks/__init__.py report_renderer/data/engine.py report_renderer/templates tests/test_redact.py tests/test_block_test_runs.py
git commit -m "Test runs block: runs of the period, tools, times and configuration with secrets hidden"
```

---

### Task 5: Renderer: data-bound options leave the blocks

**Files:**
- Modify: `report_renderer/blocks/test_results.py` (options lines 39-93, `choice_options` line 97,
  `load` line 99), `report_renderer/blocks/changes_since.py` (options lines 85-95, `choices` 100-107,
  `load` 109-125)
- Test: `tests/test_v2_test_results.py`, `tests/test_v2_changes_since.py` (or the files that hold these
  blocks' tests: `grep -ln "evaluations=\|compare_to" tests/`)

**Interfaces:**
- Produces: `test_results` has no `evaluations` option; `changes_since.compare_to` is `{"enum":
  ["previous"]}`; the version compared with is `selection.compare_to` when set, else the previous one.

- [ ] **Step 1: Write the failing tests**

```python
def test_test_results_has_no_evaluations_option(deps):
    from v2_block_helpers import block_class
    assert "evaluations" not in block_class(deps, "test_results").options_schema["properties"]


def test_changes_since_compares_with_the_selections_version(deps):
    from conftest import IDS
    from v2_block_helpers import block, v2_snapshot, render_snapshot, section, text
    b = block("changes_since")
    snap = v2_snapshot([b], project="A", system="A_V3", snapshot_version=3,
                       selection={"period_from": None, "period_to": None, "other_versions": False,
                                  "compare_to": IDS["A_V1"]})
    assert "version 1" in text(section(render_snapshot(deps, snap)["html"], b["instance_id"])).lower()
```

Rewrite each existing test that passes `evaluations=[...]` to `test_results`: give the same runs through
a selection period or statuses instead, keeping its assertion. Keep a list of the rewritten tests for
the task report.

- [ ] **Step 2: Run them to see them fail**

Expected: FAIL (the option still exists; compare_to from the selection is ignored).

- [ ] **Step 3: Implement**

`test_results.py`: delete the `evaluations` property, drop it from `default_options` and
`choice_options`, and call `load_runs(ctx, statuses=..., evaluation_pids=None, ...)`.
`changes_since.py`: `"compare_to": {"enum": ["previous"], "title": "Compare with", "description":
"The version before, or the version chosen when the report is generated."}`; `choices` returns
`[{"value": "previous", "label": "The version before"}]`; in `load`:

```python
        chosen = getattr(ctx.report.selection, "compare_to", None)
        compare_to = chosen or previous_version(ctx)          # previous_version: the existing helper
        base = ctx.data.for_version(compare_to)
```

- [ ] **Step 4: Run the whole renderer suite**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "Blocks: run ids and a fixed compare version leave the layout; the selection gives them"
```

---

### Task 6: Renderer: a chart's comments by version and period

**Files:**
- Modify: `report_renderer/data/superset_db.py` (`comments`, line 37), `report_renderer/data/platform.py`
  (new `versions`), `report_renderer/blocks/dashboard_chart.py` (`load` line 428, `render` line 452)
- Test: `tests/test_comments_by_version.py`

**Interfaces:**
- Produces: `platform.versions(project_id, system_id, *, sources) -> list[dict]` (`pid, number,
  created_at`, oldest first); `superset_db.comments(..., chart_id, since=None, until=None)`; comment
  dicts gain `version_number`.

- [ ] **Step 1: Write the failing tests** (Alpha's chart 33 comments: 09-12 10:00, reply 09-12 11:00,
  09-13 09:00, all under version 2, which runs from 09-08 to 09-15)

```python
# tests/test_comments_by_version.py
import pytest

from conftest import IDS
from v2_block_helpers import block, v2_snapshot, render_snapshot, section, text

pytestmark = pytest.mark.db


def _chart(deps, system, **sel):
    b = block("dashboard_chart", chart_id=IDS["CHART_A"], show_comments=True, include_replies=True)
    selection = {"period_from": None, "period_to": None, "other_versions": False, "compare_to": None, **sel}
    snap = v2_snapshot([b], project="A", system=system, snapshot_version=3, selection=selection)
    return text(section(render_snapshot(deps, snap)["html"], b["instance_id"]))


def test_comments_written_under_the_version_are_printed(deps):
    assert "Second root comment" in _chart(deps, "A_V2")


def test_comments_of_another_version_are_not_printed(deps):
    assert "Second root comment" not in _chart(deps, "A_V3")


def test_with_other_versions_they_are_printed_with_their_version(deps):
    t = _chart(deps, "A_V3", other_versions=True)
    assert "Second root comment" in t and "version 2" in t.lower()


def test_the_period_bounds_the_comments(deps):
    t = _chart(deps, "A_V2", period_from="2026-09-13T00:00:00+00:00", period_to="2026-09-14T00:00:00+00:00")
    assert "Second root comment" in t and "First look" not in t


def test_comments_of_another_project_never_appear(deps):
    assert "BETAMARK" not in _chart(deps, "A_V2", other_versions=True)
```

- [ ] **Step 2: Run them to see them fail**

Expected: the V3, other-versions and period tests FAIL.

- [ ] **Step 3: Implement**

`platform.py`:

```python
def versions(project_id, system_id, *, sources) -> list[dict]:
    """Every version of the project, oldest first, with the moment it was saved (comments are matched
    to the version current when they were written)."""
    return db.project_rows(sources, check_uuid(project_id), "project",
                           "SELECT pid::text, number, created_at FROM project.system ORDER BY created_at, number", {})
```

`superset_db.comments`: add `AND (%(since)s::timestamp IS NULL OR c.created_at >= %(since)s)
AND (%(until)s::timestamp IS NULL OR c.created_at < %(until)s)` with both bounds converted to naive UTC
(`created_at` is stored without time zone, read as UTC). `dashboard_chart.load`:

```python
        sel = getattr(ctx.report, "selection", None)
        rows = ctx.data.superset_db.comments(chart_id=chart_id, since=_naive(sel and sel.period_from),
                                             until=_naive(sel and sel.period_to))
        versions = ctx.data.platform.versions()
        for c in rows:
            c["version_number"] = _version_at(versions, c["created_at"])
        if not (sel and sel.other_versions):
            rows = [c for c in rows if c["version_number"] == ctx.system["number"]]
```

with `_version_at(versions, when)` returning the number of the newest version whose `created_at <=
when` (None before the first), and `_naive(dt)` returning `dt.astimezone(timezone.utc).replace(tzinfo=None)`
or None. Replies follow their root: a reply is kept when its root is kept. In `render`, a comment whose
version differs from the anchor shows "(version N)"; replace the notice "Comments are not tied to a
system version." by "Comments are matched to the version current when they were written."

- [ ] **Step 4: Run the whole renderer suite**

Expected: PASS (update any test that pinned the old notice text to the new one).

- [ ] **Step 5: Commit**

```bash
git commit -am "Dashboard chart: its comments by the version current when written, and by the period"
```

---

### Task 7: Composer: the schema without data on the layout

**Files:**
- Create: `apps/report-composer/migrations/project/0002_layouts_without_data.sql`
- Modify: `apps/report-composer/report_composer/db.py` (`DEFAULT_SETTINGS` L57, `list_layouts` L64,
  `get_layout` L76, `insert_layout` L101, `update_layout` L114, `insert_report` L200, `list_reports`
  L220, `get_report` L227), `report_composer/settings.py`
- Test: `apps/report-composer/tests/test_rm_schema.py`

**Interfaces:**
- Produces: `DEFAULT_SETTINGS = {"show_index": True, "numbering": False, "coverage": []}`;
  `insert_layout(conn, *, template_id, name, description, blocks, who, now, settings=None) -> str`;
  `update_layout(conn, layout_id, *, based_on, name, description, template_id, blocks, who, now,
  settings) -> int | None`; layout dicts have `show_index` and no `system_id`, `toc`;
  `insert_report(conn, *, layout_id, layout_revision, system_id, snapshot, created_by, created_at,
  fmt="pdf", report_id=None, period_from=None, period_to=None, other_versions=False, compare_to=None)`;
  report rows gain `system_number, period_from, period_to, other_versions, compare_number`;
  `settings.document_settings(body, current)` handles `show_index`; `settings.snapshot_document(layout,
  report_id)` returns `{"id", "toc": "on" | "off", "numbering"}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rm_schema.py
"""Layouts hold no data (report modules spec, section 7.2)."""
import pytest

from conftest import pdb_of

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _columns(bed, table):
    out = bed.psql(pdb_of("A"), "SELECT string_agg(column_name, ',' ORDER BY column_name) FROM"
                   f" information_schema.columns WHERE table_schema = 'report_composer' AND table_name = '{table}'")
    return set(out.strip().split(","))


def test_a_layout_has_no_version_language_or_toc(client, bed):
    client.get("/health")
    cols = _columns(bed, "layout")
    assert {"system_id", "language", "toc"}.isdisjoint(cols)
    assert {"show_index", "numbering", "coverage"} <= cols


def test_a_report_records_its_selection(client, bed):
    client.get("/health")
    assert {"system_id", "period_from", "period_to", "other_versions", "compare_to"} <= _columns(bed, "generated_report")


def test_the_settings_default_to_an_index_and_no_numbering():
    from report_composer.settings import document_settings, snapshot_document
    s = document_settings({}, None)
    assert (s["show_index"], s["numbering"]) == (True, False)
    assert snapshot_document({**s, "show_index": False}, None)["toc"] == "off"
    with pytest.raises(Exception):
        document_settings({"show_index": "yes"}, None)
```

Check first how `bed.psql` returns output (`grep -n "def psql" ~/aisc-definitive/scripts/lib/report_bed*.py`)
and adapt `_columns` to it; the assertion stays.

- [ ] **Step 2: Run them to see them fail**

Expected: FAIL (columns still there, `show_index` unknown).

- [ ] **Step 3: Implement**

```sql
-- migrations/project/0002_layouts_without_data.sql
-- Report modules spec 2026-09-28, section 7.2: a layout is structure only; the data a report covers
-- is chosen when it is generated and recorded on the report.
ALTER TABLE report_composer.layout ADD COLUMN show_index boolean NOT NULL DEFAULT true;
UPDATE report_composer.layout SET show_index = (toc <> 'off');
ALTER TABLE report_composer.layout
    DROP CONSTRAINT layout_toc_check, DROP COLUMN toc,
    DROP CONSTRAINT layout_language_check, DROP COLUMN language,
    DROP CONSTRAINT layout_system_id_fkey, DROP COLUMN system_id;

-- options that named one run or one version leave the layout (section 3.1)
UPDATE report_composer.layout_block SET options = options - 'evaluations' WHERE block_type = 'test_results';
UPDATE report_composer.layout_block SET options = jsonb_set(options, '{compare_to}', '"previous"')
    WHERE block_type = 'changes_since' AND options ? 'compare_to' AND options->>'compare_to' <> 'previous';

ALTER TABLE report_composer.generated_report
    ADD COLUMN period_from timestamptz,
    ADD COLUMN period_to timestamptz,
    ADD COLUMN other_versions boolean NOT NULL DEFAULT false,
    ADD COLUMN compare_to uuid CONSTRAINT generated_report_compare_to_fkey REFERENCES project.system (pid),
    ADD CONSTRAINT generated_report_period_check
        CHECK (period_from IS NULL OR period_to IS NULL OR period_from < period_to);
```

`db.py`: remove `system_id`, `toc`, the `JOIN project.system` from `list_layouts` (keep the template and
last-report joins), select `show_index` in place of `toc`; `insert_layout`/`update_layout` lose
`system_pid` and write `show_index`; `insert_report` writes the four new columns; `list_reports` and
`get_report` select them plus `s.number AS system_number` and `c.number AS compare_number` (LEFT JOIN
`project.system c ON c.pid = r.compare_to`). `settings.py`:

```python
def document_settings(body: dict, current: dict | None) -> dict:
    """The settings to store: body values checked, absent ones from `current` (or the defaults)."""
    base = {k: (current or {}).get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    out = dict(base)
    for key in ("show_index", "numbering"):
        if key in body and body[key] is not None:
            if not isinstance(body[key], bool):
                raise _invalid(f"/{key}", f"{key} must be true or false.")
            out[key] = body[key]
    if "coverage" in body and body["coverage"] is not None:
        problems = coverage_map.shape_problems(body["coverage"])
        if problems:
            raise ApiError(422, "invalid_request", "The coverage map is not valid.", problems)
        out["coverage"] = coverage_map.normalised(body["coverage"])
    return out


def snapshot_document(layout: dict, report_id: str | None) -> dict:
    """The snapshot's `document`: the renderer still speaks toc on/off."""
    return {"id": report_id, "toc": "on" if layout.get("show_index", True) else "off",
            "numbering": bool(layout.get("numbering"))}
```

Delete `TOC_VALUES`. The API and page code still pass `system_pid` and fails now: Task 8 fixes it.
Commit only when Task 8's tests pass too: this task's step 5 is folded into Task 8's commit.

- [ ] **Step 4: Run this task's tests**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rm_schema.py`
Expected: PASS.

- [ ] **Step 5: No commit yet** (the app does not start cleanly until Task 8).

---

### Task 8: Composer: the layout API without a version

**Files:**
- Modify: `report_composer/api.py` (`layout_view` L41, `POST layouts` L138-182, `_system_for_new_layout`
  L185 (delete), `PUT` L204-237, `validate` L276, `GET preview` L288, `POST preview` L317-350,
  `duplicate` L355, `export` L385; delete `POST layouts/{id}/preset` L398, `/presets*` L422-470),
  `report_composer/presets.py` (file import/export only), create `report_composer/preview_with.py`
- Modify tests: every composer test that sends or reads `system_id`, `toc`, `preset` on a layout (see
  the counts in the table below); new `tests/test_rm_layouts_api.py`

**Interfaces:**
- Consumes: Task 7's db and settings.
- Produces:
  - `POST /api/p/{ref}/layouts` body `{name, description?, template_id?, blocks?, show_index?, numbering?,
    coverage?, file?}` (`file`: a layout file, format `aisc-report-preset` v1 or v2); answers the layout
    view `{id, project_id, name, description, template_id, revision, blocks, created_at, updated_at,
    show_index, numbering, coverage}` (+ `notices` for a file).
  - `PUT` the same keys plus `revision`. `POST .../duplicate` accepts a built-in id (Task 9).
  - `preview_with.parse(conn, body) -> PreviewWith(system: dict | None, selection: dict)`: the preview's
    version (`system_id`, default the latest) and selection (`period_from`, `period_to` as dates,
    `other_versions`), never stored.
  - `GET /api/p/{ref}/layouts/{id}/export` writes format `aisc-report-preset` version 2:
    `{format, version: 2, name, description, show_index, numbering, blocks}`.
  - Removed: `POST .../preset`, `GET /presets`, `POST /presets/import`, `GET /presets/{id}/export`,
    `DELETE /presets/{id}`.

Test files to update (counts from the 2026-09-28 map: tests / lines naming system_id, preset, toc):
`test_api_layouts.py` 23/18/0/0, `test_v2_presets.py` 37/6/116/13, `test_v2_layout_settings.py` 16/9/0/11,
`test_p2_presets.py` 13/1/22/1, `test_p2_english_only.py` 18/7/21/3, `test_isolation_project_databases.py`
22/13/18/0, `test_migration_keys.py` 8/16/0/0, `test_v2_draft_preview.py` 16/3/0/3, `test_v2_pages.py`
40/9/19/0, `test_api_templates.py` 20/7/0/0, `test_pages.py` 12/6/0/0, `test_isolation_cross_project.py`
5/6/4/0, `test_layouts_unit.py` 13/4/0/0, conftest `new_layout`, `put_layout` (drop `system_id`).
Rule for each test: if it pins behaviour the spec removes (saved presets, a layout's version, toc
auto/on/off), delete it and list it in the task report with the spec section that removes it; if it pins
behaviour that stays (validation, revisions, isolation, references), keep its assertion and drop only the
removed keys.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rm_layouts_api.py
"""Layouts without data (report modules spec, sections 2, 3.1, 5)."""
import pytest

from conftest import IDS, blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def test_a_layout_is_created_without_a_version(client, auth):
    r = client.post("/api/p/alpha/layouts", json={"name": "Plain"}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert "system_id" not in body and body["show_index"] is True and body["blocks"] == []


def test_a_project_without_versions_can_have_layouts(client, auth):
    r = client.post("/api/p/gamma/layouts", json={"name": "Early"}, headers=auth("alice"))
    assert r.status_code in (201, 403)            # gamma has no project database for the composer
    # the point: never "The version is not one of this project."
    assert "version" not in r.text.lower()


def test_show_index_and_numbering_are_saved(client, auth):
    lay = new_layout(client, auth, name="Settings", show_index=False, numbering=True)
    got = client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()
    assert (got["show_index"], got["numbering"]) == (False, True)


def test_a_version_sent_by_an_old_client_is_ignored(client, auth):
    lay = new_layout(client, auth, name="Old client", system_id=IDS["A_V2"])
    assert "system_id" not in lay


def test_export_is_version_2_without_data(client, auth):
    lay = new_layout(client, auth, name="Exported", blocks=[blk("test_results", detail="summary")])
    doc = client.get(f"/api/p/alpha/layouts/{lay['id']}/export", headers=auth("alice")).json()
    assert (doc["format"], doc["version"]) == ("aisc-report-preset", 2)
    assert {"system_id", "language", "toc"}.isdisjoint(doc)


def test_an_old_preset_file_imports_with_a_notice_for_each_dropped_reference(client, auth):
    old = {"format": "aisc-report-preset", "version": 1, "name": "Old", "toc": "off", "language": "fr",
           "blocks": [{"block_type": "test_results", "options": {"evaluations": [IDS["EVAL_M_V2_PF_FULL"]]}}]}
    r = client.post("/api/p/alpha/layouts", json={"file": old}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["show_index"] is False and body["name"] == "Old"
    assert "evaluations" not in body["blocks"][0]["options"]
    assert body["notices"]


def test_the_preset_library_routes_are_gone(client, auth):
    assert client.get("/api/presets", headers=auth("alice")).status_code == 404


def test_the_draft_preview_takes_a_version_and_period_not_stored(client, auth):
    lay = new_layout(client, auth, name="Previewed", blocks=[blk("test_runs")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("alice"),
                    json={"blocks": lay["blocks"], "preview_with": {"system_id": IDS["A_V2"],
                          "period_from": "2026-09-10", "period_to": "2026-09-10", "other_versions": False}})
    assert r.status_code == 200, r.text
    again = client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()
    assert "preview_with" not in again
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rm_layouts_api.py`
Expected: FAIL (layouts still need a version; export is v1; presets routes exist).

- [ ] **Step 3: Implement**

`report_composer/preview_with.py`:

```python
"""What a preview is drawn with: a version and a period, chosen in the editor's preview pane and
never saved in the layout (report modules spec, section 5)."""
from __future__ import annotations

from dataclasses import dataclass

from . import db, selection


@dataclass(frozen=True)
class PreviewWith:
    system: dict | None          # None: the project has no version yet
    selection: dict              # the snapshot's `selection` object


def parse(conn, body: dict | None) -> PreviewWith:
    body = body or {}
    system = db.system_of_project(conn, body["system_id"]) if body.get("system_id") else db.latest_system(conn)
    if body.get("system_id") and system is None:
        system = db.latest_system(conn)          # a stale choice falls back to the latest
    sel = selection.parse_dates(body.get("period_from"), body.get("period_to"),
                                bool(body.get("other_versions")), None)
    return PreviewWith(system=system, selection=selection.for_snapshot(sel))
```

`report_composer/selection.py` (shared with Task 11; create it here):

```python
"""The data a report covers (report modules spec, section 6). Dates are inclusive, in UTC: a period
runs from 00:00 of `from` to 00:00 of the day after `to`."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from .errors import ApiError


@dataclass(frozen=True)
class Selection:
    period_from: datetime | None
    period_to: datetime | None
    other_versions: bool
    compare_to: str | None


def _day(value, pointer) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError(422, "invalid_request", "A date is YYYY-MM-DD.", [{"pointer": pointer,
                       "message": "is not a date"}]) from None


def parse_dates(from_value, to_value, other_versions: bool, compare_to) -> Selection:
    start, end = _day(from_value, "/period_from"), _day(to_value, "/period_to")
    if start and end and end < start:
        raise ApiError(422, "invalid_request", "The period ends before it starts.",
                       [{"pointer": "/period_to", "message": "is before the start"}])
    pf = datetime.combine(start, time(0), timezone.utc) if start else None
    pt = datetime.combine(end + timedelta(days=1), time(0), timezone.utc) if end else None
    return Selection(pf, pt, bool(other_versions), compare_to)


def for_snapshot(sel: Selection) -> dict:
    iso = lambda d: d.isoformat() if d else None
    return {"period_from": iso(sel.period_from), "period_to": iso(sel.period_to),
            "other_versions": sel.other_versions, "compare_to": sel.compare_to}


def last_day(period_to: datetime | None) -> date | None:
    """The inclusive last day of a stored period."""
    return (period_to - timedelta(days=1)).date() if period_to else None
```

`api.py`:
- `layout_view`: return the keys listed in Produces (no `system_id`, `toc`; add `show_index`).
- `post_layout`: sources are `file` or `blocks` (at most one); no `system_id`, no `preset`; a file goes
  through `presets.from_file(body["file"], types)` then `presets.blocks_for_layout`; without either, an
  empty block list. Validation: `layouts.validate_layout(blocks, block_types=types, choices=lambda t: {},
  allow_missing_references=True, coverage=settings["coverage"], coverage_choices=None)`: shape and types
  only; references are checked at preview and generation (spec 3.1).
- `put_layout`: same validation; a `system_id` in the body is ignored.
- `validate`, `GET preview`, `POST preview`: take `preview_with` (POST body key, GET query params
  `system_id`, `period_from`, `period_to`, `other_versions`), check references with
  `choices_for(request, pid, pw.system["pid"])` and `coverage_choices_for(...)` when `pw.system` is not
  None; with no version, answer a preview page with the text "This project has no AI card version yet.
  Save the AI card in qualification first." without calling the renderer.
- `snapshot_of` (reports.py) takes `system_id` and `selection` arguments (Task 11 uses the same
  signature): `snapshot_of(project, layout, mode, caller, template=None, *, system_id, selection,
  document_id=None)`, with `"snapshot_version": 3`, `"system_id": system_id`, `"selection": selection`.
- `duplicate`: copies `show_index, numbering, coverage`, no version.
- `export`: `presets.export_doc(presets.from_layout(...))` with `FILE_VERSION = 2`.
- Delete the preset library routes and `may_delete_preset`; `presets.from_file` accepts versions 1 and 2
  (v1's `toc` maps to `show_index = toc != "off"`, `language` is dropped), and its reference reset also
  drops `test_results.evaluations` and a non-"previous" `changes_since.compare_to` with a notice each.

Then update the listed test files by the rule above, and `pages.py` so the pages still render (the
layouts and editor pages are redone in Tasks 10 and 12; here only stop reading `system_id`/`toc`).

- [ ] **Step 4: Run the whole composer suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_e2e.py --ignore=tests/test_e2e_v2.py`
Expected: PASS but the known isolation failure (Global Constraints).

- [ ] **Step 5: Commit (Tasks 7 and 8)**

```bash
cd ~/aisc-definitive && git add apps/report-composer
git commit -m "Composer: layouts hold no data (no version, no language, index on or off); preset library routes gone"
```

---

### Task 9: Composer: five built-in layouts, listed and duplicated

**Files:**
- Delete: `report_composer/presets/{full-assessment,eu-ai-act,internal-audit,executive-summary}.json`
- Create: `report_composer/presets/{summary,management-overview,assessment-report,eu-ai-act,technical-dossier}.json`,
  `report_composer/builtin_layouts.py`
- Modify: `report_composer/presets.py` (`BUILT_IN_ORDER`, `built_in`), `report_composer/api.py`
  (`duplicate`, new `GET /api/p/{ref}/builtin-layouts`, `GET /api/p/{ref}/builtin-layouts/{id}/export`)
- Test: `tests/test_rm_builtins.py`

**Interfaces:**
- Produces: `builtin_layouts.ORDER = ("summary", "management-overview", "assessment-report",
  "eu-ai-act", "technical-dossier")`; `builtin_layouts.all_layouts(block_types) -> list[dict]` (layout
  views with `id = "builtin-<slug>"`, `built_in: True`, `revision: 0`, deterministic instance ids
  `uuid5(NAMESPACE_URL, f"aisc-builtin/{slug}/{i}")`); `builtin_layouts.get(layout_id, block_types) ->
  dict | None`; `POST /api/p/{ref}/layouts/builtin-<slug>/duplicate` makes a project layout.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rm_builtins.py
"""The five built-in layouts (report modules spec, section 4.1)."""
import pytest

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

LEVELS = ["Summary", "Management overview", "Assessment report", "EU AI Act conformity", "Technical dossier"]


def _builtins(client, auth):
    r = client.get("/api/p/alpha/builtin-layouts", headers=auth("alice"))
    assert r.status_code == 200, r.text
    return r.json()


def test_five_levels_in_order(client, auth):
    assert [b["name"] for b in _builtins(client, auth)] == LEVELS


def test_each_level_holds_more_modules_than_the_one_before(client, auth):
    counts = [len(b["blocks"]) for b in _builtins(client, auth)]
    assert counts == sorted(counts) and len(set(counts)) == 5


def test_the_summary_is_the_four_modules_of_the_spec(client, auth):
    s = _builtins(client, auth)[0]
    assert [b["block_type"] for b in s["blocks"]] == ["cover", "key_figures", "summary_coverage", "changes_since"]
    assert s["blocks"][2]["options"]["show_uncovered_only"] is True


def test_no_built_in_names_data(client, auth):
    for b in _builtins(client, auth):
        for block in b["blocks"]:
            assert block["block_type"] != "dashboard_chart"
            assert "evaluations" not in block["options"]
            assert block["options"].get("compare_to", "previous") == "previous"


def test_the_technical_dossier_shows_full_configuration(client, auth):
    runs = [b for b in _builtins(client, auth)[4]["blocks"] if b["block_type"] == "test_runs"]
    assert {"configuration": "full", "detail": "full"}.items() <= runs[-1]["options"].items()


def test_duplicate_makes_an_editable_project_layout(client, auth):
    r = client.post("/api/p/alpha/layouts/builtin-assessment-report/duplicate", json={}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    assert r.json()["name"].startswith("Assessment report") and "built_in" not in r.json()


def test_built_ins_cannot_be_changed(client, auth):
    r = client.put("/api/p/alpha/layouts/builtin-summary", json={"name": "x", "revision": 0, "blocks": []},
                   headers=auth("alice"))
    assert r.status_code in (404, 409)
```

- [ ] **Step 2: Run them to see them fail**

Expected: FAIL (route missing, four old presets).

- [ ] **Step 3: Implement**

Write the five JSON files from spec section 4.1, format `{"format": "aisc-report-preset", "version": 2,
"id", "name", "description", "show_index", "numbering", "blocks": [{"block_type", "options"}]}`. Option
values per module (names from the renderer's schemas):
- Summary: `show_index: false`; cover; key_figures `{"figures": ["version", "risks", "objectives",
  "coverage", "tests"]}`; summary_coverage `{"show_uncovered_only": true}`; changes_since
  `{"compare_to": "previous", "show_unchanged": false}`.
- Management overview: cover; key_figures `{"show_tool_headlines": true}`; ai_card
  `{"show_components": false, "show_tags": false, "show_graph_stats": false}`; risk_classification
  `{"show_chains": false, "show_impact_areas": true}`; chart `{"dataset": "coverage_status"}`;
  summary_coverage `{"show_uncovered_only": true}`; changes_since.
- Assessment report: cover; key_figures; chapter `{"title": "The AI system"}`; ai_card
  `{"show_components": true}`; risk_classification `{"show_chains": true}`; chapter `{"title": "Control
  objectives"}`; control_objectives `{"group_by": "objective", "show_status": true, "show_severity":
  true}`; summary_coverage `{"show_uncovered_only": false}`; chapter `{"title": "Tests"}`; test_runs
  `{"detail": "summary", "configuration": "none"}`; test_results `{"detail": "summary"}`; chart
  `{"dataset": "metric_by_evaluation"}`; changes_since.
- EU AI Act conformity: cover; free_text `{"title": "Scope"}` (placeholder text, as the old presets);
  key_figures; chapter "The AI system": ai_card `{"show_components": true, "show_tags": true}`,
  risk_classification `{"show_chains": true, "show_impact_areas": true}`; chapter "Control objectives":
  control_objectives `{"show_rationale": true, "show_severity": true, "include_unrated": true}`,
  control_answers `{"show_scores": true}`, summary_coverage; chapter "Evidence": test_runs `{"detail":
  "summary", "configuration": "summary"}`, test_results `{"detail": "full"}`, chart `{"dataset":
  "metric_by_evaluation"}`, chart `{"dataset": "checklist_scores"}`; changes_since; free_text `{"title":
  "Findings"}`; appendix; free_text `{"title": "Method"}`.
- Technical dossier: level 4 with control_objectives `{"group_by": "risk", "show_quotes": true, ...}`,
  control_answers `{"show_unanswered": true, "include_archived": true, "show_scores": true}`,
  test_results `{"detail": "full", "statuses": <every status in the renderer's STATUSES>}`, extra charts
  `{"dataset": "metric_by_dimension"}` and `{"dataset": "tool_chart"}`, changes_since `{"show_unchanged":
  true}`; appendix: free_text "Method", ai_card `{"show_graph_stats": true, "show_components": false,
  "show_tags": false}`, test_runs `{"detail": "full", "configuration": "full"}`.

Check each file validates: every option must pass the block's schema (a test in step 1 loads them
through the API, which validates). Where a schema requires more (chart datasets require `metric` for
some datasets: see `_requires` in `blocks/chart.py`), pick the dataset's documented default or drop that
chart and say so in the task report.

`builtin_layouts.py`:

```python
"""The five built-in layouts (report modules spec, section 4.1): read-only, shared by every project,
opened to inspect and duplicated to adapt. They are files; nothing is stored for them."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import presets

DIRECTORY = Path(__file__).resolve().parent / "presets"
ORDER = ("summary", "management-overview", "assessment-report", "eu-ai-act", "technical-dossier")
PREFIX = "builtin-"


def _view(slug: str, block_types) -> dict:
    doc = json.loads((DIRECTORY / f"{slug}.json").read_text(encoding="utf-8"))
    blocks = [{"instance_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"aisc-builtin/{slug}/{i}")),
               "block_type": b["block_type"], "options": presets.with_defaults(b, block_types)}
              for i, b in enumerate(doc["blocks"])]
    return {"id": PREFIX + slug, "name": doc["name"], "description": doc.get("description", ""),
            "built_in": True, "revision": 0, "template_id": None, "show_index": doc.get("show_index", True),
            "numbering": doc.get("numbering", False), "coverage": [], "blocks": blocks}


def all_layouts(block_types) -> list[dict]:
    return [_view(s, block_types) for s in ORDER]


def get(layout_id: str, block_types) -> dict | None:
    slug = layout_id[len(PREFIX):] if layout_id.startswith(PREFIX) else None
    return _view(slug, block_types) if slug in ORDER else None
```

`presets.with_defaults(block, block_types)`: the block's options merged over its type's
`default_options` (extract it from `blocks_for_layout`, which already does this merge). In `api.py`
`duplicate`: when `layout_id` starts with `builtin-`, the source is `builtin_layouts.get(...)` (404 when
None); the copy gets new instance ids and the name `presets.copy_name(src["name"], taken)`. `PUT` and
`DELETE` on a `builtin-` id answer 404 (they go through `layout_or_404`, which rejects non-uuids).
Remove `BUILT_IN_ORDER` and `built_in*` from `presets.py`.

- [ ] **Step 4: Run the whole composer suite**

Expected: PASS but the known failure.

- [ ] **Step 5: Commit**

```bash
git add apps/report-composer && git commit -m "Five built-in layouts at increasing detail replace the four presets; duplicate a built-in"
```

---

### Task 10: Composer: the layouts page

**Files:**
- Modify: `report_composer/pages.py` (`layouts_page` L63-77), `report_composer/templates/layouts.html.j2`,
  `report_composer/static/composer.js` (layouts part, L109-162), `report_composer/static/composer.css`
- Test: `tests/test_rm_layouts_page.py`

**Interfaces:**
- Consumes: `builtin_layouts.all_layouts` (Task 9), `db.list_layouts` (Task 7).
- Produces: page `/p/{slug}/` with header actions `data-control="start-new-layout"` (link to
  `/p/{slug}/layouts/new`) and `data-control="import-layout"` (form with a file input, uploads on pick);
  one table: built-ins first (a "Built-in" badge), then the project's; row actions `open-layout`,
  `duplicate`, `export-structure`; no Delete, no Version column, no Start from, no Save as preset, no
  Presets section.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rm_layouts_page.py
import pytest

from conftest import new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _page(client, auth, who="alice"):
    return soup(client.get("/p/alpha/", headers=auth(who)).text)


def test_new_and_import_are_the_pages_actions(client, auth):
    actions = _page(client, auth).find(class_="rc-header").find(class_="page-actions")
    assert actions.find("a", attrs={"data-control": "start-new-layout"})["href"].endswith("/p/alpha/layouts/new")
    imp = actions.find("form", attrs={"data-control": "import-layout"})
    assert imp.find("input", attrs={"type": "file"}) is not None and imp.find("button") is None


def test_built_ins_and_project_layouts_in_one_list(client, auth):
    new_layout(client, auth, name="Mine")
    rows = _page(client, auth).select("table.layouts tbody tr")
    names = [r.find("td").get_text(" ", strip=True) for r in rows]
    assert names[:5] == ["Summary Built-in", "Management overview Built-in", "Assessment report Built-in",
                         "EU AI Act conformity Built-in", "Technical dossier Built-in"]
    assert names[5] == "Mine"


def test_the_old_controls_are_gone(client, auth):
    doc = _page(client, auth)
    text = doc.get_text()
    assert "Start from" not in text and "Save as preset" not in text and "Presets" not in text
    for control in ("save-preset", "delete", "import-preset", "new-layout"):
        assert doc.find(attrs={"data-control": control}) is None, control
    assert "Version" not in [th.get_text(strip=True) for th in doc.select("table.layouts th")]


def test_a_viewer_can_open_and_export_but_not_create(client, auth):
    doc = _page(client, auth, who="victor")
    assert doc.find(attrs={"data-control": "start-new-layout"}) is None
    assert doc.find(attrs={"data-control": "open-layout"}) is not None
```

- [ ] **Step 2: Run them to see them fail**

- [ ] **Step 3: Implement**

`pages.layouts_page` passes `builtins=builtin_layouts.all_layouts(block_types(request))` and `layouts`;
drop `systems`, `built_in_presets`, `saved_presets`. Template: header row as in `templates.html.j2`
(`rc-header rc-header-row`, `page-actions` with the New link and the import form), then one
`<table class="layouts">` with columns Layout, Template, Revision, Updated, Last report, actions. A
built-in row: name + `<span class="badge">Built-in</span>`, Template "Platform default", Revision
"built-in", actions Open (`/p/{slug}/layouts/builtin-<slug>`), Duplicate (editors), Export
(`/api/p/{slug}/builtin-layouts/builtin-<slug>/export`). `composer.js` layouts part: delete the
`new-layout`, `import-preset`, `save-preset-form`, `save-preset`, `cancel-preset`, `delete-preset`
handlers and `presetForm`; add the import (one change listener as on the templates page, then `POST
/layouts {file: doc}` and go to `/p/{slug}/layouts/{id}`); `duplicate` goes to the new layout's editor
(`location.href = base + "/layouts/" + res.data.id`). CSS: `.badge` (small, uppercase, primary border).

- [ ] **Step 4: Run the composer suite; check the script length**

Run: `... pytest -q -p no:cacheprovider tests/test_rm_layouts_page.py tests/test_pages.py tests/test_v2_pages.py` and `wc -l report_composer/static/composer.js` (under 500).

- [ ] **Step 5: Commit**

```bash
git add apps/report-composer && git commit -m "Layouts page: New and Import in the header, built-ins and project layouts in one list"
```

---

### Task 11: Composer: generating a report from a selection

**Files:**
- Modify: `report_composer/reports.py` (`snapshot_of` L61, `_start` L84, `generate` L112),
  `report_composer/api.py` (`POST reports` L473, `GET reports` L484)
- Test: `tests/test_rm_reports.py`

**Interfaces:**
- Consumes: `selection.parse_dates`, `selection.for_snapshot` (Task 8), db report functions (Task 7).
- Produces: `reports.generate(request, project, layout_id, caller, fmt="pdf", *, choice: dict) ->
  (status, body)` where `choice = {system_id, period_from, period_to, other_versions, compare_to}`
  (dates as `YYYY-MM-DD` or empty); `reports.check_choice(conn, layout, choice) -> (system: dict,
  sel: Selection)` raising `ApiError`; `POST /api/p/{ref}/layouts/{id}/reports` body `{format,
  system_id, period_from, period_to, other_versions, compare_to}`; `GET .../reports` rows with
  `system_number, period_from, last_day, other_versions, compare_number`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rm_reports.py
import pytest

from conftest import IDS, blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _generate(client, auth, lay, **choice):
    body = {"format": "pdf", **choice}
    return client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json=body, headers=auth("alice"))


def test_a_report_needs_a_version(client, auth):
    lay = new_layout(client, auth, name="Needs", blocks=[blk("cover")])
    r = _generate(client, auth, lay)
    assert r.status_code == 422 and "system_id" in r.text


def test_the_selection_is_sent_and_recorded(client, auth, fake_renderer):
    lay = new_layout(client, auth, name="Chosen", blocks=[blk("cover")])
    r = _generate(client, auth, lay, system_id=IDS["A_V2"], period_from="2026-09-10", period_to="2026-09-10",
                  other_versions=True)
    assert r.status_code == 201, r.text
    snap = fake_renderer.last_snapshot
    assert snap["snapshot_version"] == 3 and snap["system_id"] == IDS["A_V2"]
    assert snap["selection"] == {"period_from": "2026-09-10T00:00:00+00:00",
                                 "period_to": "2026-09-11T00:00:00+00:00", "other_versions": True,
                                 "compare_to": None}
    row = client.get(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("alice")).json()[0]
    assert (row["system_number"], row["period_from"][:10], row["last_day"], row["other_versions"]) == \
        (2, "2026-09-10", "2026-09-10", True)


def test_a_version_of_another_project_is_refused(client, auth):
    lay = new_layout(client, auth, name="Foreign", blocks=[blk("cover")])
    r = _generate(client, auth, lay, system_id=IDS["B_V1"])
    assert r.status_code == 422


def test_compare_to_must_be_an_older_version(client, auth):
    lay = new_layout(client, auth, name="Compare", blocks=[blk("changes_since")])
    r = _generate(client, auth, lay, system_id=IDS["A_V2"], compare_to=IDS["A_V3"])
    assert r.status_code == 422


def test_an_upside_down_period_is_refused(client, auth):
    lay = new_layout(client, auth, name="Upside", blocks=[blk("cover")])
    r = _generate(client, auth, lay, system_id=IDS["A_V2"], period_from="2026-09-12", period_to="2026-09-10")
    assert r.status_code == 422
```

Use the composer's fake renderer fixture (`grep -n "def fake_renderer\|last_snapshot\|class Fake" tests/conftest.py tests/v2_fakes.py`);
if it does not record the last snapshot, add `last_snapshot` to it.

- [ ] **Step 2: Run them to see them fail**

- [ ] **Step 3: Implement**

`reports.py`:

```python
def check_choice(conn, layout, choice: dict):
    """The version and the selection a report is generated for (report modules spec, section 6)."""
    if not choice.get("system_id"):
        raise ApiError(422, "invalid_request", "Choose the AI card version to report on.",
                       [{"pointer": "/system_id", "message": "is required"}])
    system = db.system_of_project(conn, choice["system_id"])
    if system is None:
        raise ApiError(422, "system_not_in_project", "The version is not one of this project.")
    compare_to = choice.get("compare_to") or None
    if compare_to is not None:
        older = db.system_of_project(conn, compare_to)
        if older is None or older["number"] >= system["number"]:
            raise ApiError(422, "invalid_request", "Compare with an earlier version of this project.",
                           [{"pointer": "/compare_to", "message": "is not an earlier version"}])
    sel = selection.parse_dates(choice.get("period_from"), choice.get("period_to"),
                                bool(choice.get("other_versions")), compare_to)
    return system, sel
```

`_start(request, conn, project, layout_id, caller, fmt, choice)`: after the layout checks, `system, sel
= check_choice(conn, layout, choice)`; validate references with `choices_for(request, project["pid"],
system["pid"])` and `coverage_choices_for(..., system["pid"])`; `snapshot_of(project, layout, fmt,
caller, template, system_id=system["pid"], selection=selection.for_snapshot(sel),
document_id=report_id)`; `db.insert_report(..., system_id=system["pid"], period_from=sel.period_from,
period_to=sel.period_to, other_versions=sel.other_versions, compare_to=sel.compare_to)`. `generate`
passes `choice` through. `api.post_report` reads the choice keys from the body; `GET reports` adds
`last_day = selection.last_day(row["period_to"])`.

- [ ] **Step 4: Run the composer suite**

- [ ] **Step 5: Commit**

```bash
git add apps/report-composer && git commit -m "Reports: generated for a chosen version, period, other-versions switch and compare version"
```

---

### Task 12: Composer: the layout editor and the Generate page

**Files:**
- Create: `report_composer/groups.py`, `report_composer/templates/generate.html.j2`
- Modify: `report_composer/pages.py` (`editor_page` L106-140, new `new_layout_page`, `generate_page`,
  `generate_submit`), `report_composer/templates/editor.html.j2` (toolbar L22-32, palette, reports list
  L107-114), `report_composer/static/composer.js` (editor part L205-498), `report_composer/static/composer.css`
- Test: `tests/test_rm_editor_page.py`, `tests/test_rm_generate_page.py`

**Interfaces:**
- Consumes: Tasks 8, 9, 11.
- Produces:
  - `groups.GROUPS: list[tuple[str, tuple[str, ...]]]` = `[("AI card", ("ai_card", "risk_classification")),
    ("Control objectives", ("control_objectives", "control_answers", "summary_coverage")), ("Tests run",
    ("test_runs",)), ("Results", ("test_results", "dashboard_chart", "chart")), ("Summary", ("key_figures",
    "changes_since")), ("Document", ("cover", "chapter", "free_text", "appendix"))]`;
    `groups.palette(types) -> list[dict]` (`{"label", "types": [...]}`, unknown types under "Other").
  - Editor page `/p/{slug}/layouts/{id}`, `/p/{slug}/layouts/new`, `/p/{slug}/layouts/builtin-<slug>`
    (read-only: no palette, no Save, no Delete; buttons Duplicate, Export).
  - Toolbar: name, template, `show_index` checkbox ("Index"), `numbering` checkbox ("Numbering"), Save,
    Generate report (a link to the Generate page), Delete (editors, saved layouts only, with confirm).
  - Preview pane: "Preview with" form (GET, same page): version select, from, to, other versions;
    its values reach the script through `main[data-preview-with]` (JSON) and are sent as `preview_with`.
  - Generate page `/p/{slug}/layouts/{id}/generate`: GET draws the form (version select required, newest
    first; from; to; "Include runs made against other versions"; "Compare with" only when the layout has
    `changes_since`; format pdf or docx); POST (form fields) calls `reports.generate(..., choice=...)`,
    then redirects 303 to `/p/{slug}/layouts/{id}#reports`; a refused choice redraws the form with the
    message; a project without versions shows the message of spec section 6 and no Generate button.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rm_generate_page.py
import pytest

from conftest import IDS, blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def test_the_form_asks_for_version_period_switch_and_format(client, auth):
    lay = new_layout(client, auth, name="G", blocks=[blk("cover")])
    doc = soup(client.get(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice")).text)
    form = doc.find("form", attrs={"data-control": "generate-report"})
    versions = [o.get_text(strip=True) for o in form.find("select", attrs={"name": "system_id"}).find_all("option")]
    assert versions[0].startswith("Version 3")                   # newest first
    for name in ("period_from", "period_to", "other_versions", "format"):
        assert form.find(attrs={"name": name}) is not None, name
    assert form.find(attrs={"name": "compare_to"}) is None       # no Changes since in this layout


def test_compare_with_appears_with_changes_since(client, auth):
    lay = new_layout(client, auth, name="C", blocks=[blk("changes_since")])
    doc = soup(client.get(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice")).text)
    assert doc.find(attrs={"name": "compare_to"}) is not None


def test_submitting_generates_and_goes_back_to_the_layout(client, auth, fake_renderer):
    lay = new_layout(client, auth, name="S", blocks=[blk("cover")])
    r = client.post(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice"), follow_redirects=False,
                    data={"system_id": IDS["A_V2"], "period_from": "2026-09-10", "period_to": "",
                          "format": "pdf"})
    assert r.status_code == 303 and r.headers["location"].endswith(f"/p/alpha/layouts/{lay['id']}#reports")


def test_an_upside_down_period_redraws_the_form_with_the_message(client, auth):
    lay = new_layout(client, auth, name="U", blocks=[blk("cover")])
    r = client.post(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice"),
                    data={"system_id": IDS["A_V2"], "period_from": "2026-09-12", "period_to": "2026-09-10",
                          "format": "pdf"})
    assert r.status_code == 422 and "The period ends before it starts." in r.text


def test_a_cross_origin_post_is_refused(client, auth):
    lay = new_layout(client, auth, name="X", blocks=[blk("cover")])
    r = client.post(f"/p/alpha/layouts/{lay['id']}/generate", headers={**auth("alice"), "Origin": "https://evil.test"},
                    data={"system_id": IDS["A_V2"], "format": "pdf"})
    assert r.status_code == 403
```

```python
# tests/test_rm_editor_page.py
import pytest

from conftest import blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def test_the_palette_is_grouped(client, auth):
    lay = new_layout(client, auth, name="P")
    doc = soup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text)
    labels = [h.get_text(strip=True) for h in doc.select("[data-palette] .palette-group > h3")]
    assert labels[:6] == ["AI card", "Control objectives", "Tests run", "Results", "Summary", "Document"]


def test_the_toolbar_has_index_and_numbering_and_no_version(client, auth):
    lay = new_layout(client, auth, name="T")
    tb = soup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text).find(class_="toolbar")
    assert tb.find("input", attrs={"name": "show_index", "type": "checkbox"}) is not None
    assert tb.find("input", attrs={"name": "numbering", "type": "checkbox"}) is not None
    assert tb.find(attrs={"data-control": "version"}) is None and tb.find(attrs={"data-control": "toc"}) is None
    assert tb.find("a", attrs={"data-control": "open-generate"})["href"].endswith(f"/layouts/{lay['id']}/generate")
    assert tb.find(attrs={"data-control": "delete-layout"}) is not None


def test_a_built_in_opens_read_only(client, auth):
    doc = soup(client.get("/p/alpha/layouts/builtin-summary", headers=auth("alice")).text)
    assert doc.find(attrs={"data-control": "save"}) is None and doc.find(attrs={"data-palette": True}) is None
    assert doc.find(attrs={"data-control": "duplicate"}) is not None
    assert "Summary" in doc.find("h1").get_text()


def test_the_new_layout_page_is_the_editor_with_nothing_saved(client, auth):
    doc = soup(client.get("/p/alpha/layouts/new", headers=auth("alice")).text)
    main = doc.find("main")
    assert main["data-page"] == "editor" and not main.get("data-layout")
    assert doc.find(attrs={"data-control": "delete-layout"}) is None


def test_the_preview_with_choice_reaches_the_script(client, auth):
    import json
    from conftest import IDS
    lay = new_layout(client, auth, name="W")
    doc = soup(client.get(f"/p/alpha/layouts/{lay['id']}?system_id={IDS['A_V2']}&period_from=2026-09-10",
                          headers=auth("alice")).text)
    pw = json.loads(doc.find("main")["data-preview-with"])
    assert pw["system_id"] == IDS["A_V2"] and pw["period_from"] == "2026-09-10"


def test_without_a_version_generate_explains():
    # every seeded project with a composer database has versions, so the page's context helper is tested
    from report_composer.pages import generate_context
    ctx = generate_context(layout={"blocks": []}, systems=[])
    assert ctx["message"] == "This project has no AI card version yet. Save the AI card in qualification first."
```

- [ ] **Step 2: Run them to see them fail**

- [ ] **Step 3: Implement**

`groups.py`:

```python
"""The module groups of the layout editor's palette (report modules spec, section 3)."""
from __future__ import annotations

GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("AI card", ("ai_card", "risk_classification")),
    ("Control objectives", ("control_objectives", "control_answers", "summary_coverage")),
    ("Tests run", ("test_runs",)),
    ("Results", ("test_results", "dashboard_chart", "chart")),
    ("Summary", ("key_figures", "changes_since")),
    ("Document", ("cover", "chapter", "free_text", "appendix")),
]


def palette(types: list[dict]) -> list[dict]:
    by_id = {t["type_id"]: t for t in types}
    out, placed = [], set()
    for label, ids in GROUPS:
        members = [by_id[i] for i in ids if i in by_id]
        placed.update(ids)
        if members:
            out.append({"label": label, "types": members})
    rest = [t for t in types if t["type_id"] not in placed]
    if rest:
        out.append({"label": "Other", "types": rest})
    return out
```

`pages.py`:
- `generate_context(layout, systems, error=None, form=None) -> dict`: `{"systems": systems (newest
  first), "has_changes_since": any(b["block_type"] == "changes_since" for b in layout["blocks"]),
  "message": None if systems else "This project has no AI card version yet. Save the AI card in
  qualification first.", "error": error, "form": form or {}}`.
- `@router.get("/p/{ref}/layouts/{layout_id}/generate")` (editor right): draws `generate.html.j2`.
- `@router.post("/p/{ref}/layouts/{layout_id}/generate")`: `g = guard(request, ref, "editor")` (its
  origin check refuses a foreign Origin); `form = await request.form()`; `choice = {k: form.get(k) or None
  for k in ("system_id", "period_from", "period_to", "compare_to")} | {"other_versions":
  form.get("other_versions") == "on"}`; `fmt = form.get("format") if form.get("format") in ("pdf",
  "docx") else "pdf"`; `status, body = reports.generate(request, g.project, layout_id, g.caller, fmt,
  choice=choice)` inside `try/except ApiError as e` (on error: redraw with `error=e.message`, status
  `e.status`); on success `RedirectResponse(f"{_root(request)}/p/{slug}/layouts/{layout_id}#reports",
  303)`; a renderer failure (status >= 500) redraws with the error text.
- `editor_page`: `layout_id == "new"` renders an unsaved editor (`layout=None`); a `builtin-` id uses
  `builtin_layouts.get` and `read_only=True`; otherwise the project layout. It passes
  `palette=groups.palette(types)`, `preview_with` (the query params `system_id`, `period_from`,
  `period_to`, `other_versions`, as a dict, JSON-encoded into `data-preview-with`) and the reports list
  with the Task 11 columns. Reference choices for the configure forms come from the preview's version
  (`preview_with.parse`).
- `editor.html.j2`: toolbar as in Produces; palette as `<section data-palette>` with one
  `<div class="palette-group"><h3>{{ g.label }}</h3>...</div>` per group; the "Preview with" form above
  the preview iframe (method GET, fields as above, a "Show" button); reports table columns: Created,
  Version, Period (`from` to `last_day`, or "All runs"), Other versions (Yes/No), Compare with,
  Status, Download.
- `generate.html.j2`: `<form method="post" data-control="generate-report">` with the fields of Produces;
  the version select lists "Version N (release)" newest first; an error paragraph `role="alert"` when
  `error`; the message and no submit button when `message`.
- `composer.js` editor part: `editorState()` sends `{template_id, show_index: checked, numbering:
  checked, coverage, blocks}` (no `system_id`, `toc`); `refresh()` adds `preview_with:
  JSON.parse(main.dataset.previewWith || "{}")`; `save()` POSTs to `/layouts` when `main.dataset.layout`
  is empty and then goes to the new layout's page, otherwise PUTs as today; delete the generate
  handlers (generation is the Generate page); add `delete-layout` (askFor, then `DELETE`, then go to the
  layouts page); a read-only page has no editor state (the script returns early when
  `main.dataset.readOnly`). Keep the file under 500 lines: `wc -l`.

- [ ] **Step 4: Run the composer suite; check the script length**

- [ ] **Step 5: Commit**

```bash
git add apps/report-composer && git commit -m "Layout editor: grouped palette, index and numbering, preview with a version and period; Generate report page"
```

---

### Task 13: Browser tests of the flows

**Files:**
- Create: `apps/report-composer/tests/test_rm_browser.py` (reuse the `live` fixture pattern of
  `tests/test_templates_browser.py`, including its `api()` block for same-origin API calls)

**Interfaces:**
- Consumes: every page of Tasks 10-12.

- [ ] **Step 1: Write the tests**

```python
def test_new_layout_save_then_generate(live):
    page = live("/p/alpha/")
    page.click('.page-actions [data-control="start-new-layout"]')
    page.wait_for_url("**/layouts/new")
    page.fill('input[name="name"]', "Browser layout")
    page.click('[data-palette] button[data-add="cover"]')
    page.click('[data-control="save"]')
    page.wait_for_url(lambda u: "/layouts/new" not in u and "/layouts/" in u, timeout=5000)
    page.click('[data-control="open-generate"]')
    page.select_option('select[name="system_id"]', index=0)
    page.click('form[data-control="generate-report"] button[type="submit"]')
    page.wait_for_url("**#reports", timeout=10000)
    assert page.locator("[data-reports] tbody tr").count() == 1


def test_duplicate_a_built_in_opens_its_copy(live):
    page = live("/p/alpha/layouts/builtin-assessment-report")
    page.click('[data-control="duplicate"]')
    page.wait_for_url(lambda u: "builtin-" not in u, timeout=5000)
    assert "Assessment report" in page.locator('input[name="name"]').input_value()


def test_import_a_file_opens_the_imported_layout(live, tmp_path):
    import json
    from conftest import IDS
    old = {"format": "aisc-report-preset", "version": 1, "name": "Imported old", "toc": "off",
           "blocks": [{"block_type": "test_results", "options": {"evaluations": [IDS["EVAL_M_V2_PF_FULL"]]}}]}
    file = tmp_path / "old.json"
    file.write_text(json.dumps(old))
    page = live("/p/alpha/")
    page.set_input_files('.page-actions [data-control="import-layout"] input[type="file"]', str(file))
    page.wait_for_url(lambda u: "/layouts/" in u and "/layouts/new" not in u, timeout=5000)
    assert page.locator('input[name="name"]').input_value() == "Imported old"
    assert page.locator('input[name="show_index"]').is_checked() is False
```

The `live` fixture is the one of `tests/test_templates_browser.py`, changed so `open(path)` takes the
page path (`/p/alpha/...`) instead of a templates query.

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rm_browser.py`
Expected: PASS, no JavaScript errors.

- [ ] **Step 3: Commit**

```bash
git add apps/report-composer/tests/test_rm_browser.py && git commit -m "Browser tests: new layout to report, duplicate a built-in, import an old file"
```

---

### Task 14: The whole-branch check and the docs

**Files:**
- Modify: `apps/report-composer/README.md` (layouts, built-ins, generation), the renderer's `README.md`
  (the `selection`, `test_runs`), and the spec's section 11 if anything was decided during the tasks.

- [ ] **Step 1: Run every suite**

```bash
cd ~/aisc-report-generator && env -u DATABASE_URL -u PLATFORM_TEST_DATABASE_URL AISC_INSTALL_DIR=$HOME/aisc-definitive uv run --extra dev pytest -q -p no:cacheprovider
cd ~/aisc-definitive/apps/report-composer && .venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_e2e.py --ignore=tests/test_e2e_v2.py
```
Expected: renderer green; composer green but the known failure.

- [ ] **Step 2: Run the e2e tests against a real renderer** (they start one: read `tests/test_e2e_v2.py`
  for what it needs) and fix what they find.

- [ ] **Step 3: Update the READMEs; commit in each repo**

```bash
cd ~/aisc-report-generator && git commit -am "README: the data selection and the Test runs block"
cd ~/aisc-definitive && git add apps/report-composer/README.md && git commit -m "Composer README: layouts without data, built-ins, generating a report"
```

---

### Task 15: Deploy to the running stack (ask first)

The running stack is compose project `aisc-adapt` from `~/aisc-adapt`, started by another session.

- [ ] **Step 1: Ask the user** whether to deploy there now, naming what restarts (`report-composer`,
  `report-renderer`) and that `~/aisc-adapt` would need these commits (copy or pull from
  `~/aisc-definitive` and `~/aisc-report-generator`). Stop until the answer.
- [ ] **Step 2: On a yes:** bring the commits into `~/aisc-adapt`, rebuild and restart only those two
  services (`docker compose -p aisc-adapt ... build report-composer report-renderer` then `up -d --no-deps`),
  check both are healthy and the composer's migration 0002 ran in the Demo project database.
- [ ] **Step 3: Report** what was deployed, what was checked, and what was not (a signed-in click-through
  needs the browser extension).

---

### Task 16: Drop the saved-preset library (ask first)

- [ ] **Step 1: Ask the user** to confirm the drop of `report_library.preset` (platform database, 0 rows
  on the running stack on 2026-09-28). Stop until the answer.
- [ ] **Step 2: On a yes, write the failing test**

```python
# tests/test_rm_library_dropped.py
import pytest

pytestmark = pytest.mark.db


def test_the_preset_library_table_is_gone(client, bed):
    client.get("/health")
    out = bed.psql("platform", "SELECT to_regclass('report_library.preset') IS NULL")
    assert out.strip() in ("t", "true")
```

- [ ] **Step 3: Implement** `migrations/library/0002_no_preset_library.sql`:

```sql
-- Report modules spec 2026-09-28, sections 4 and 7.3: layouts are shared by export and import; the
-- install-wide preset library is gone. Confirmed by the user before this migration was written.
DROP TABLE report_library.preset;
```

Remove `db.list_presets`, `get_preset`, `preset_names`, `insert_preset`, `delete_preset`, `_PRESET`.

- [ ] **Step 4: Run the composer suite; commit**

```bash
git add apps/report-composer && git commit -m "Drop the saved-preset library (confirmed by the user)"
```
