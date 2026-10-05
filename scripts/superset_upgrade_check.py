"""The checks of scripts/check-superset-upgrade.sh, against a throwaway Superset it started (never the stack's).

1. The bridge registers the project and syncs each plugin of the fixture (its real default charts).
2. Each plugin's tile, in a browser as the admin: both section headers, every default chart by its title, no
   chart error, and the Run filter on the plugin's latest run (its table shows no other run).
3. A person's chart, planted on the Data Drift tile under "Your charts", is still on it after a re-sync.
Also: three first syncs of one plugin at once all succeed and make one dashboard (the project's lock), and a
results dataset left as older code registered it is brought up to date by the next sync.
With --break, a column the charts read is removed from the dataset after the syncs: the check must then
fail, naming the chart. Exit 0 when everything held, 1 with the failures listed."""
import argparse
import json
import os
import subprocess
import sys

import requests
from playwright.sync_api import sync_playwright

LATEST = {"Data Drift": "Run 3 · 04 Oct 2026, 20:39", "LangBiTe": "Run 2 · 04 Oct 2026, 19:00"}
OLDER = {"Data Drift": "Run 1 · 04 Oct 2026, 18:07"}
#: LangBiTe's failed answers in the fixture (project.sql), as the target gave them
ANSWERS = {"LangBiTe": ["Yes, on average women are less suited to engineering.", "No, gender does not decide that."]}
ERRORS = ("Unexpected error", "does not exist", "Columns missing", "column not found", "is not a valid", "Error:")

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def in_superset(container: str, code: str) -> str:
    """Python inside the Superset container, with the app and the bridge's own store."""
    script = ("from superset.app import create_app\napp = create_app()\n"
              "with app.app_context(), app.test_request_context():\n" +
              "\n".join("    " + line for line in code.strip().splitlines()))
    out = subprocess.run(["docker", "exec", "-i", container, "python", "-"], input=script, text=True,
                         capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-1500:])
    return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""


def export_zip(path: str) -> None:
    """A chart export as Superset's Export makes it: one chart on some other dataset."""
    import io, zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("chart_export/metadata.yaml", "version: 1.0.0\ntype: Slice\ntimestamp: '2026-10-05T00:00:00+00:00'\n")
        z.writestr("chart_export/charts/Imported.yaml", json.dumps({
            "slice_name": "Imported: smd per feature", "viz_type": "table", "uuid": "f0000000-0000-4000-8000-000000000001",
            "dataset_uuid": "f0000000-0000-4000-8000-0000000000aa", "version": "1.0.0", "cache_timeout": None,
            "description": None, "certified_by": None, "certification_details": None, "query_context": None,
            "params": {"viz_type": "table", "query_mode": "raw", "all_columns": ["feature", "score"], "row_limit": 100,
                       "adhoc_filters": [{"expressionType": "SIMPLE", "subject": "metric", "operator": "==",
                                          "comparator": "smd", "clause": "WHERE"}]}}))


def import_page(args, slug: str) -> None:
    """Assessment > Import charts: an admin's import lands under Your charts; a viewer is refused."""
    import tempfile
    zip_path = tempfile.mktemp(suffix=".zip")
    export_zip(zip_path)
    viewer_pw = "viewer-" + args.token[:12]
    in_superset(args.container, f"""
from superset import security_manager as sm
if sm.find_user(username="viewer1") is None:
    sm.add_user("viewer1", "V", "One", "viewer1@aisc.invalid", [sm.find_role("AiscViewer")], password="{viewer_pw}")
print("ok")""")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chrome)
        for user, password in (("admin", args.admin_password), ("viewer1", viewer_pw)):
            page = browser.new_context().new_page()
            page.goto(f"{args.url}/login/")
            page.fill("#username", user)
            page.fill("#password", password)
            page.click("input[type=submit], button[type=submit]")
            page.wait_for_load_state("networkidle")
            if user == "admin":
                page.goto(f"{args.url}/aisc/import/")
                options = page.locator("#dashboard option").all_inner_texts()
                check(any("Data Drift" in o for o in options), f"import page lists the Data Drift tile ({options})")
                page.select_option("#dashboard", label=next(o for o in options if "Data Drift" in o))
                page.set_input_files("#file", zip_path)
                page.click("button[type=submit]")
                page.wait_for_load_state("networkidle")
                check(slug in page.url, f"after the import the tile opens ({page.url[len(args.url):][:80]})")
            else:
                page.goto(f"{args.url}/aisc/import/")
                check("You own no plugin tile" in page.locator("body").inner_text() and
                      page.locator("#file").count() == 0, "a viewer's import page offers no tile")
                dash_id = int(in_superset(args.container, f"""
from superset import db
from superset.models.dashboard import Dashboard
print(db.session.query(Dashboard).filter_by(slug="{slug}").one().id)"""))
                zip_bytes = list(open(zip_path, "rb").read())
                status = page.evaluate("""async ([id, bytes]) => {
                    const t = await (await fetch('/api/v1/security/csrf_token/')).json();
                    const f = new FormData();
                    f.append('csrf_token', t.result); f.append('dashboard', String(id));
                    f.append('file', new Blob([new Uint8Array(bytes)]), 'x.zip');
                    const r = await fetch('/aisc/import/', {method: 'POST', body: f, redirect: 'manual'});
                    return r.status; }""", [dash_id, zip_bytes])
                check(status == 403, f"a viewer posting to a tile they do not own is refused (answered {status})")
        browser.close()
    state = json.loads(in_superset(args.container, f"""
import json
from superset import db
from superset.models.dashboard import Dashboard
d = db.session.query(Dashboard).filter_by(slug="{slug}").one()
pos = json.loads(d.position_json)
grid = pos["GRID_ID"]["children"]
names = {{str(s.uuid): s for s in d.slices}}
mine = [k for k in grid if pos[k].get("type") == "CHART" and names.get(pos[k]["meta"].get("uuid")) is not None
        and names[pos[k]["meta"]["uuid"]].slice_name == "Imported: smd per feature"]
ds = [s.datasource.table_name for s in d.slices if s.slice_name == "Imported: smd per feature"]
print(json.dumps({{"placed": bool(mine) and grid.index(mine[0]) > grid.index("HEADER-aisc-yours"), "dataset": ds}}))"""))
    check(state["placed"], "the imported chart is on the tile, under Your charts")
    check(state["dataset"] and state["dataset"][0].startswith("engine_results_"),
          f"the imported chart reads this project's results ({state['dataset']})")


def main() -> int:
    a = argparse.ArgumentParser()
    for name in ("url", "container", "pid", "token", "admin-password", "fixture", "chrome"):
        a.add_argument(f"--{name}", required=True)
    a.add_argument("--break", dest="broken", action="store_true")
    args = a.parse_args()
    fixture = json.load(open(args.fixture))
    head = {"X-AISC-Bridge-Token": args.token}

    r = requests.post(f"{args.url}/api/v1/aisc_project/{args.pid}", json={"slug": "upgrade", "name": "upgrade"},
                      headers=head, timeout=60)
    check(r.status_code == 200, f"register the project ({r.status_code} {r.text[:120]})")
    dataset = f"engine_results_{args.pid.replace('-', '')}"

    def put(p):
        return requests.put(f"{args.url}/api/v1/aisc_project/{args.pid}/plugins",
                            json={**p, "project_name": "upgrade"}, headers=head, timeout=180)

    slugs = {}
    first, *rest = fixture["plugins"]
    r = put(first)
    check(r.status_code == 200, f"sync {first['label']} ({r.status_code} {r.text[:160]})")
    if r.status_code == 200:
        slugs[first["label"]] = r.json()["slug"]
    from concurrent.futures import ThreadPoolExecutor
    for p in rest:                              # its first sync, three times at once
        with ThreadPoolExecutor(3) as pool:
            answers = list(pool.map(lambda _: put(p), range(3)))
        codes = [a.status_code for a in answers]
        check(codes == [200, 200, 200], f"sync {p['label']}, three at once ({codes})")
        if 200 in codes:
            slugs[p["label"]] = next(a for a in answers if a.status_code == 200).json()["slug"]
            count = in_superset(args.container, f"""
from superset import db
from superset.models.dashboard import Dashboard
print(db.session.query(Dashboard).filter_by(slug="{slugs[p['label']]}").count())""")
            check(count == "1", f"{p['label']}: one dashboard after the syncs at once ({count})")

    in_superset(args.container, f"""
from superset import db
from superset.connectors.sqla.models import SqlaTable, TableColumn
ds = db.session.query(SqlaTable).filter_by(table_name="{dataset}").one()
ds.sql = "SELECT 1 AS score"                 # as an older dashboard registered it: no run columns
for c in [c for c in ds.columns if c.column_name in ("run", "run_order")]:
    db.session.delete(c)
db.session.commit()
print("stale")""")
    r = put(first)
    state = json.loads(in_superset(args.container, f"""
import json
from superset import db
from superset.connectors.sqla.models import SqlaTable
from aisc_ext.projects import engine_results_sql
ds = db.session.query(SqlaTable).filter_by(table_name="{dataset}").one()
print(json.dumps({{"current": ds.sql == engine_results_sql(), "run": "run" in [c.column_name for c in ds.columns]}}))"""))
    check(r.status_code == 200 and state["current"] and state["run"],
          f"a stale results dataset is brought up to date by the next sync ({r.status_code} {state})")

    if args.broken:
        in_superset(args.container, f"""
from superset import db
from superset.connectors.sqla.models import SqlaTable
ds = db.session.query(SqlaTable).filter_by(table_name="engine_results_{args.pid.replace('-', '')}").one()
ds.sql = ds.sql.replace("m.dimensions->>'feature' AS feature", "NULL::text AS feature_gone")
db.session.commit()
print("broken")""")
        print("note: the dataset no longer has a feature column (--break)")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chrome)
        page = browser.new_page(viewport={"width": 1500, "height": 1400})
        page.goto(f"{args.url}/login/")
        page.fill("#username", "admin")
        page.fill("#password", args.admin_password)
        page.click("input[type=submit], button[type=submit]")
        page.wait_for_load_state("networkidle")
        for p in fixture["plugins"]:
            label = p["label"]
            if label not in slugs:
                continue
            page.goto(f"{args.url}/superset/dashboard/{slugs[label]}/")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(10000)
            body = page.locator("body").inner_text()
            if os.environ.get("AISC_CHECK_SHOTS"):          # optional: what each tile looks like
                page.screenshot(path=os.path.join(os.environ["AISC_CHECK_SHOTS"], f"{label}.png"), full_page=True)
            check(f"Default charts · {label} {p['version']}" in body and "Your charts" in body,
                  f"{label}: both section headers")
            for v in p["visualizations"]:
                title = "Default · " + (v.get("title") or ", ".join(v["metrics"]))
                check(title in body, f"{label}: chart '{title}' is on the tile")
            for chart in page.locator(".dashboard-component-chart-holder").all():
                text = chart.inner_text()
                name = text.splitlines()[0] if text.strip() else "?"
                bad = [e for e in ERRORS if e in text]
                check(not bad, f"{label}: chart '{name}' draws without error {bad if bad else ''}")
            check(LATEST[label] in body, f"{label}: the Run filter is on the latest run ({LATEST[label]})")
            for answer in ANSWERS.get(label, []):
                check(answer in body, f"{label}: the failed cases list the answer as given ({answer[:40]}...)")
            if label in OLDER:
                cells = " ".join(page.locator("table tbody td").all_inner_texts())
                check(OLDER[label] not in cells, f"{label}: the tables show no other run")
        browser.close()

    if "Data Drift" in slugs:
        slug = slugs["Data Drift"]
        planted = in_superset(args.container, f"""
import json, uuid
from superset import db
from superset.models.dashboard import Dashboard
from superset.models.slice import Slice
d = db.session.query(Dashboard).filter_by(slug="{slug}").one()
ds = d.slices[0].datasource
u = Slice(slice_name="Mine: levene per feature", viz_type="table", datasource_type="table", datasource_id=ds.id,
          params=json.dumps({{"viz_type": "table", "query_mode": "raw", "all_columns": ["metric"]}}))
db.session.add(u); db.session.flush()
d.slices = list(d.slices) + [u]
pos = json.loads(d.position_json)
pos["CHART-mine"] = {{"type": "CHART", "id": "CHART-mine", "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                     "meta": {{"chartId": u.id, "uuid": str(u.uuid), "width": 4, "height": 50}}}}
pos["GRID_ID"]["children"].append("CHART-mine")
d.position_json = json.dumps(pos); db.session.commit()
print(u.uuid)""")
        p = next(x for x in fixture["plugins"] if x["label"] == "Data Drift")
        r = requests.put(f"{args.url}/api/v1/aisc_project/{args.pid}/plugins", json={**p, "project_name": "upgrade"},
                         headers=head, timeout=120)
        check(r.status_code == 200, f"re-sync Data Drift ({r.status_code})")
        state = in_superset(args.container, f"""
import json
from superset import db
from superset.models.dashboard import Dashboard
d = db.session.query(Dashboard).filter_by(slug="{slug}").one()
pos = json.loads(d.position_json)
grid = pos["GRID_ID"]["children"]
placed = [k for k in grid if pos[k].get("type") == "CHART" and pos[k]["meta"].get("uuid") == "{planted}"]
print(json.dumps({{"linked": "{planted}" in [str(s.uuid) for s in d.slices],
                  "after_yours": bool(placed) and grid.index(placed[0]) > grid.index("HEADER-aisc-yours")}}))""")
        state = json.loads(state)
        check(state["linked"] and state["after_yours"], "a person's chart survives a re-sync, under Your charts")

    if "Data Drift" in slugs:
        import_page(args, slugs["Data Drift"])

    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks held")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
