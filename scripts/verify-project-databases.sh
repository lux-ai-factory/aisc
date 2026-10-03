#!/usr/bin/env bash
# Is every project completely isolated in its own database? Each check prints its label, I16.x.
#
#   ./scripts/verify-project-databases.sh                  # I16.1 .. I16.7
#   ./scripts/verify-project-databases.sh --privileges     # only I16.1 and I16.2 (the cutover runs this)
#   ./scripts/verify-project-databases.sh --final-layout   # also I16.2's exact layout after stage 7
#
# What it proves, against the cluster PG* points at (the running stack's Postgres by default):
#   I16.1 privileges: in platform every role has exactly its listed rights (PLATFORM_TABLES); in
#         each project_<hex> database each module role has rights on its own schema only, USAGE on
#         project and SELECT, REFERENCES on project.system, nothing on llm, provision or another
#         module; the readers (report_ro, dashboard_ro) read exactly READER_TABLES and nothing by a
#         default privilege; PUBLIC may not connect; inspector_ro writes nothing
#   I16.2 placement: the retired module schemas of platform (and core.system) are unreachable by
#         every role but the superuser and inspector_ro (pg_read_all_data, by design); with
#         --final-layout platform has exactly PLATFORM_SCHEMAS and core its three tables
#   I16.3 every project has its database, with every template file, every module at its head,
#         unique positive card version numbers, and every system_id resolving in the same database
#   I16.4 the running containers' DSNs name project databases (docker inspect; values are never
#         printed, only the database part). VERIFY_SKIP_CONTAINERS=1 skips it
#   I16.5 two throwaway projects A and B through the APIs; what is made in A is absent from B's
#         database and 404 under B's pid (VERIFY_BASE_URL, VERIFY_ACCESS_TOKEN of a member, read
#         from the environment and never printed). No token is a FAIL, never a silent pass;
#         VERIFY_SKIP_FUNCTIONAL=1 skips it
#   I16.6 scripts/db_consistency, whose exit status counts
#   I16.7 (projects x VERIFY_PER_PROJECT_CONNECTIONS) + VERIFY_BASE_CONNECTIONS under 80% of
#         max_connections, else a WARN (never a failure)
#
# Read-only: every session is default_transaction_read_only=on and only SELECTs are sent (the
# functional part writes through the APIs only, and takes its two projects away afterwards).
# Output lines are "  PASS|FAIL|WARN I16.x <text>"; exit status 1 on any FAIL. Every check runs
# even after an earlier one failed.
#
# Connection: PGHOST (127.0.0.1), PGPORT (5432), PGUSER (aisc-postgres-user) and PGPASSWORD, read
# from the postgres container's environment when unset. It is never printed. The host has no psql:
# the SQL runs from the Python below, with psycopg.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
export PGHOST=${PGHOST:-127.0.0.1} PGPORT=${PGPORT:-5432} PGUSER=${PGUSER:-aisc-postgres-user}
export PGDATABASE=${PGDATABASE:-platform}
if [ -z "${PGPASSWORD:-}" ]; then
  PGPASSWORD=$(docker exec "${PGCONTAINER:-postgres}" printenv POSTGRES_PASSWORD 2>/dev/null) || {
    echo "no PGPASSWORD, and none readable from the ${PGCONTAINER:-postgres} container" >&2; exit 2; }
  export PGPASSWORD
fi
for a in "$@"; do
  case "$a" in
    --privileges|--final-layout) ;;
    -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done
cd "$HERE" && exec uv run --no-project --quiet --with 'psycopg[binary]' python - "$@" <<'PY'
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit

import psycopg

sys.path.insert(0, os.getcwd())
from db_consistency import heads  # noqa: E402

ARGS = set(sys.argv[1:])
PRIVILEGES_ONLY = "--privileges" in ARGS
FINAL_LAYOUT = "--final-layout" in ARGS
PROJECT_DB = re.compile(r"^project_[0-9a-f]{32}$")
READ_ONLY = "-c default_transaction_read_only=on"
FAILED = []


def say(level, req, text):
    print(f"  {level} {req} {text}", flush=True)
    if level == "FAIL":
        FAILED.append(req)


def rows(db, sql, params=None):
    with psycopg.connect("", dbname=db, options=READ_ONLY, autocommit=True, connect_timeout=10) as conn:
        return conn.execute(sql, params).fetchall()


def one(db, sql, params=None):
    r = rows(db, sql, params)
    return r[0][0] if r else None


def exists(db, rel):
    return one(db, "SELECT to_regclass(%s) IS NOT NULL", (rel,))


def roles():
    return {r[0] for r in rows("platform", "SELECT rolname FROM pg_roles")}


def projects():
    """(pid, slug, database) of every core.project."""
    return [(p, s, "project_" + p.replace("-", "")) for p, s in rows(
        "platform", "SELECT pid::text, slug FROM core.project ORDER BY pid")]


def databases():
    return {r[0] for r in rows("platform", "SELECT datname FROM pg_database")}


# The lists the checks compare with.

MODULE_ROLES = ["qualification_rw", "control_objectives_rw", "controls_rw", "engine_rw", "report_composer_rw",
                "catalogue_rw"]
#: what a role may do on tables of platform it does not own
PLATFORM_TABLES = {r: {("core.project", "SELECT"), ("core.project_member", "SELECT")} for r in MODULE_ROLES}
PLATFORM_TABLES["dashboard_ro"] = {("core.project_member", "SELECT")}
PLATFORM_TABLES["report_ro"] = {("core.project", "SELECT")}
#: the platform schema each of these roles holds by design (its owner, or made for it)
HOLDS = {"report_composer_rw": "report_library", "catalogue_rw": "catalogue"}
#: the schemas of platform in the final layout
PLATFORM_SCHEMAS = {"core", "catalogue", "report_library", "public"}
CORE_TABLES = {"project", "project_member", "schema_migration"}
#: module schema of a project database -> its role
MODULES = {"qualification": "qualification_rw", "control_objectives": "control_objectives_rw",
           "engine": "engine_rw", "report_composer": "report_composer_rw", "controls": "controls_rw"}
READERS = ("report_ro", "dashboard_ro")
#: what the readers may read, exhaustive
READER_TABLES = {
    "project": ["system"],
    "controls": ["checklist", "checklist_question", "source", "submission", "submission_answer"],
    "qualification": ["qualification", "qualification_answer", "qualification_risk", "knowledge_graph",
                      "card_component", "question_set", "question_set_version", "question_set_version_item",
                      "question", "questionnaire", "questionnaire_version", "questionnaire_version_item"],
    "control_objectives": ["project", "graph", "risk", "mapped_objective", "mapping_run"],
    "engine": ["aisc_backend_project", "aisc_backend_aisystem", "aisc_backend_aicomponent", "aisc_backend_evaluation",
               "aisc_backend_evaluationplugin", "aisc_backend_evaluationinput", "aisc_backend_plugin", "aisc_backend_observation",
               "aisc_backend_measurement", "aisc_backend_metric", "aisc_backend_direct", "aisc_backend_derived",
               "aisc_backend_metriccategory", "aisc_backend_metriccategory_metrics", "aisc_backend_artifact"],
    "report_composer": [], "llm": [], "connection": [], "provision": [], "target": ["target"],
}
PLUGIN_CONFIG_COLUMNS = ("id", "plugin_id")
#: table-level rights has_table_privilege is asked about; the rest are read with aclexplode
TABLE_RIGHTS = ("SELECT", "INSERT", "UPDATE", "DELETE", "REFERENCES", "TRIGGER")
WRITE_RIGHTS = ("INSERT", "UPDATE", "DELETE")
#: (table, id column, version column): every module row that names a card version
STAMPED = (("qualification.qualification", "id", "system_id"), ("control_objectives.project", "id", "system_id"),
           ("report_composer.layout", "id", "system_id"), ("report_composer.generated_report", "id", "system_id"),
           ("engine.aisc_backend_evaluation", "pid", "system_id"), ("controls.submission_answer", "id", "system_version_pid"))


def other_rights(db, role, where):
    """(relation, right) of the rights has_table_privilege is not asked about (the rights beyond TABLE_RIGHTS),
    read from the tables' acl for `role` itself."""
    return rows(db, f"""
        SELECT n.nspname || '.' || c.relname, a.privilege_type
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
               aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
         WHERE a.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)
           AND a.privilege_type <> ALL (%s) AND c.relowner <> a.grantee AND ({where})
         ORDER BY 1, 2""", (role, list(TABLE_RIGHTS)))


def table_rights(db, role, where):
    """{(relation, right)} of tables `role` does not own, matching `where`."""
    got = {(r, p) for r, p in rows(db, f"""
        SELECT n.nspname || '.' || c.relname, p.right_name
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
               unnest(%s::text[]) AS p(right_name)
         WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
           AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname !~ '^pg_'
           AND pg_get_userbyid(c.relowner) <> %s AND ({where})
           AND has_table_privilege(%s, c.oid, p.right_name)""", (list(TABLE_RIGHTS), role, role))}
    return got | {(r, p) for r, p in other_rights(db, role, where)}


# I16.1: privileges

def i16_1_platform(present):
    ok = True
    for role, want in PLATFORM_TABLES.items():
        if role not in present:
            continue
        held = HOLDS.get(role, "")
        got = table_rights("platform", role, "n.nspname <> '%s'" % held)
        for rel, right in sorted(got - want):
            ok = False
            say("FAIL", "I16.1", f"platform: {role} has {right} on {rel}, beyond I1.4")
        for rel, right in sorted(want - got):
            ok = False
            say("FAIL", "I16.1", f"platform: {role} lacks {right} on {rel} (I1.4)")
        for schema, usage, create in rows("platform", """
                SELECT n.nspname, has_schema_privilege(%s, n.oid, 'USAGE'), has_schema_privilege(%s, n.oid, 'CREATE')
                  FROM pg_namespace n
                 WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                   AND pg_get_userbyid(n.nspowner) <> %s AND n.nspname <> %s ORDER BY 1""",
                (role, role, role, held)):
            if create:
                ok = False
                say("FAIL", "I16.1", f"platform: {role} may create in schema {schema}")
            if usage and schema not in ("core", "public"):
                ok = False
                say("FAIL", "I16.1", f"platform: {role} has USAGE on schema {schema}, beyond I1.4")
    if ok:
        say("PASS", "I16.1", "platform: every role has exactly what I1.4 allows")


def i16_1_project(db, present):
    ok = True
    schemas = {r[0] for r in rows(db, "SELECT nspname FROM pg_namespace")}
    for schema, role in MODULES.items():
        if role not in present:
            continue
        if schema in schemas:
            for right in ("USAGE", "CREATE"):
                if not one(db, "SELECT has_schema_privilege(%s, %s, %s)", (role, schema, right)):
                    ok = False
                    say("FAIL", "I16.1", f"{db}: {role} lacks {right} on its schema {schema}")
        if "project" in schemas and not one(db, "SELECT has_schema_privilege(%s, 'project', 'USAGE')", (role,)):
            ok = False
            say("FAIL", "I16.1", f"{db}: {role} lacks USAGE on schema project")
        if exists(db, "project.system"):
            for right in ("SELECT", "REFERENCES"):
                if not one(db, "SELECT has_table_privilege(%s, 'project.system', %s)", (role, right)):
                    ok = False
                    say("FAIL", "I16.1", f"{db}: {role} lacks {right} on project.system")
            for rel, right in sorted(table_rights(db, role, "n.nspname = 'project'")):
                if right not in ("SELECT", "REFERENCES"):
                    ok = False
                    say("FAIL", "I16.1", f"{db}: {role} has {right} on {rel}; only platform_rw writes it")
        for other in [*MODULES, "llm", "connection", "provision", "target"]:
            if other == schema or other not in schemas:
                continue
            for right in ("USAGE", "CREATE"):
                if one(db, "SELECT has_schema_privilege(%s, %s, %s)", (role, other, right)):
                    ok = False
                    say("FAIL", "I16.1", f"{db}: {role} has {right} on schema {other}")
    guarded = [s for s in READER_TABLES if s in schemas]
    for reader in READERS:
        if reader not in present:
            continue
        listed = {f"{s}.{t}" for s, ts in READER_TABLES.items() for t in ts}
        where = "n.nspname = ANY (ARRAY[%s])" % ", ".join(f"'{s}'" for s in guarded) if guarded else "false"
        got = table_rights(db, reader, where)
        for rel, right in sorted(got):
            if right == "SELECT" and rel in listed:
                continue
            ok = False
            say("FAIL", "I16.1", f"{db}: {reader} has {right} on {rel}, beyond the I2.6 list")
        readable = {rel for rel, right in got if right == "SELECT"}
        for rel in sorted(listed - readable):
            if exists(db, rel):
                ok = False
                say("FAIL", "I16.1", f"{db}: {reader} cannot read {rel} of the I2.6 list")
        if exists(db, "engine.aisc_backend_pluginconfig"):
            for column, want in [*[(c, True) for c in PLUGIN_CONFIG_COLUMNS], ("config", False)]:
                has = one(db, "SELECT has_column_privilege(%s, 'engine.aisc_backend_pluginconfig', %s, 'SELECT')", (reader, column))
                if has != want:
                    ok = False
                    say("FAIL", "I16.1", f"{db}: {reader} {'cannot' if want else 'can'} read engine.aisc_backend_pluginconfig.{column}")
        for owner, schema in rows(db, """
                SELECT pg_get_userbyid(d.defaclrole), coalesce(d.defaclnamespace::regnamespace::text, '(all)')
                  FROM pg_default_acl d, aclexplode(d.defaclacl) a
                 WHERE a.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)""", (reader,)):
            ok = False
            say("FAIL", "I16.1", f"{db}: {reader} is given tables by a default privilege of {owner} in {schema}")
    if one("platform", """SELECT EXISTS (SELECT 1 FROM pg_database d,
                aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a
               WHERE d.datname = %s AND a.grantee = 0 AND a.privilege_type = 'CONNECT')""", (db,)):
        ok = False
        say("FAIL", "I16.1", f"{db}: PUBLIC may connect")
    if ok:
        say("PASS", "I16.1", f"{db}: module roles, readers and PUBLIC have exactly what I16.1 allows")


def i16_1_inspector(dbs, present):
    if "inspector_ro" not in present:
        return
    bad = []
    for db in dbs:
        where = "n.nspname NOT IN ('pg_catalog', 'information_schema')"
        bad += [f"{db} {rel} {right}" for rel, right in table_rights(db, "inspector_ro", where)
                if right not in ("SELECT", "REFERENCES", "TRIGGER")]
    if bad:
        for b in bad:
            say("FAIL", "I16.1", f"inspector_ro may write: {b}")
    else:
        say("PASS", "I16.1", "inspector_ro writes nothing")


# I16.2: placement

def i16_2(present):
    ok = True
    others = sorted(r for r in present if not r.startswith("pg_") and r != "inspector_ro"
                    and not one("platform", "SELECT rolsuper FROM pg_roles WHERE rolname = %s", (r,)))
    schemas = [r[0] for r in rows("platform", """SELECT nspname FROM pg_namespace
                 WHERE nspname !~ '^pg_' AND nspname <> 'information_schema' ORDER BY 1""")]
    stray = [s for s in schemas if s not in PLATFORM_SCHEMAS]
    for schema in stray:
        for role in others:
            for right in ("USAGE", "CREATE"):
                if one("platform", "SELECT has_schema_privilege(%s, %s, %s)", (role, schema, right)):
                    ok = False
                    say("FAIL", "I16.2", f"platform schema {schema} (outside I1.3) is reachable: {role} has {right}")
            for rel, right in sorted(table_rights("platform", role, "n.nspname = '%s'" % schema.replace("'", "''"))):
                ok = False
                say("FAIL", "I16.2", f"platform {rel} (outside I1.3): {role} has {right}")
    if exists("platform", "core.system"):
        for role in others:
            for rel, right in sorted(table_rights("platform", role, "n.nspname = 'core' AND c.relname = 'system'")):
                ok = False
                say("FAIL", "I16.2", f"platform core.system is reachable: {role} has {right}")
    if FINAL_LAYOUT:
        if set(schemas) != PLATFORM_SCHEMAS:
            ok = False
            say("FAIL", "I16.2", f"platform schemas are {', '.join(schemas)}, not exactly those of I1.3")
        core = {r[0] for r in rows("platform", "SELECT relname FROM pg_class WHERE relnamespace = 'core'::regnamespace"
                                               " AND relkind IN ('r', 'p')")}
        if core != CORE_TABLES:
            ok = False
            say("FAIL", "I16.2", f"core has {', '.join(sorted(core))}, not exactly its three tables")
    if ok:
        say("PASS", "I16.2", "the retired schemas are unreachable (inspector_ro reads everything through"
                             " pg_read_all_data by design, I11.1, and is not counted)"
                             + ("; platform has exactly the layout of I1.3" if FINAL_LAYOUT else ""))


# I16.3: every project has its database, at head

def i16_3(project_list, dbs):
    """Every core.project has its database; provision.template_migration equals the repository's
    template list and every module tracker is at its head (db_consistency.heads); project.system
    numbers are unique and positive; every system_id resolves in the same database."""
    ok = True
    trackers = heads.trackers()
    for pid, slug, db in project_list:
        if db not in dbs:
            ok = False
            say("FAIL", "I16.3", f"core.project {pid} ({slug}) has no database {db}")
            continue
        for tracker in trackers:
            if not exists(db, tracker.table):
                ok = False
                say("FAIL", "I16.3", f"{db}: {tracker.module} has no {tracker.table}")
                continue
            applied = {r[0] for r in rows(db, tracker.sql)}
            lacking = heads.behind(tracker, applied)
            stray = heads.extra(tracker, applied)
            if lacking or stray:
                ok = False
                what = "template" if tracker.module == "template" else tracker.module
                say("FAIL", "I16.3", f"{db}: {what} is not at its head ({tracker.table} lacks "
                                     f"{', '.join(lacking) or '-'}; at {', '.join(stray) or '-'})")
        if exists(db, "project.system"):
            for number, count in rows(db, "SELECT number, count(*) FROM project.system GROUP BY number"
                                          " HAVING count(*) > 1 OR number <= 0 ORDER BY 1"):
                ok = False
                say("FAIL", "I16.3", f"{db}: project.system number {number} is not unique and positive ({count} rows)")
            for table, key, column in STAMPED:
                if not exists(db, table):
                    continue
                for rid, sid in rows(db, f"""SELECT t.{key}::text, t.{column}::text FROM {table} t
                        LEFT JOIN project.system s ON s.pid = t.{column}
                         WHERE t.{column} IS NOT NULL AND s.pid IS NULL ORDER BY 1"""):
                    ok = False
                    say("FAIL", "I16.3", f"{db}: {table} {rid} names {column} {sid}, not a project.system here")
    if ok:
        say("PASS", "I16.3", f"{len(project_list)} projects: each has its database, at every head, versions resolve")


# I16.4: the containers name project databases

#: container -> the variables that may name `platform` (as scripts/tests/test_compose_isolation.py)
CONTAINERS = {
    "qualification-web": set(),
    "control-objectives": {"DATABASE_URL"},
    "aisc-backend": {"DB_NAME"},
    "report-composer": {"REPORT_COMPOSER_DATABASE_URL"},
    "report-renderer": {"REPORT_PLATFORM_DATABASE_URL"},
    "dashboard": {"AISC_MEMBERSHIP_DB_URI"},
}
DSN_NAME = re.compile(r"(_URL|_URI|_DSN|_TEMPLATE)$")


def _database_part(value):
    """Only the database part of a DSN; the rest (user, password, host) is dropped here."""
    try:
        return urlsplit(value).path.lstrip("/").split("?")[0]
    except ValueError:
        return ""


def i16_4():
    """Each container's environment, read with docker inspect, reduced to database names."""
    if os.environ.get("VERIFY_SKIP_CONTAINERS") == "1":
        say("WARN", "I16.4", "not run (VERIFY_SKIP_CONTAINERS=1)")
        return
    ok = True
    for name, allowed in CONTAINERS.items():
        r = subprocess.run(["docker", "inspect", name, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            ok = False
            say("FAIL", "I16.4", f"{name}: container not found")
            continue
        env = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        per_project = False
        for var, value in sorted(env.items()):
            if var == "DB_NAME":
                database = value
            elif DSN_NAME.search(var) and "://" in value:
                database = _database_part(value)
            else:
                continue
            if "{database}" in database or database.startswith("project_"):
                per_project = True
            elif database == "platform" and var not in allowed:
                ok = False
                say("FAIL", "I16.4", f"{name}: {var} names platform, which only {', '.join(sorted(allowed))} may")
        # the engine names its project databases itself (projectdb.database_name); the dashboard's are
        # Superset connections made per project
        if not per_project and name not in ("aisc-backend", "dashboard"):
            ok = False
            say("FAIL", "I16.4", f"{name}: no DSN names {{database}} or a project_ database")
    if ok:
        say("PASS", "I16.4", "every module's DSNs name project databases; platform only where I16.4 allows")


# I16.5: two projects through the APIs

def _http(method, path, token, body=None, project=None, form=False):
    base = os.environ.get("VERIFY_BASE_URL", "http://localhost:8100").rstrip("/")
    headers = {"Authorization": "Bearer " + token}
    data = None
    if body is not None:
        if form:
            data = "&".join(f"{k}={v}" for k, v in body.items()).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    if project:
        headers["X-AISC-Project"] = project
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            text = res.read().decode(errors="replace")
            return res.status, (json.loads(text) if text[:1] in "[{" else text)
    except urllib.error.HTTPError as exc:
        return exc.code, None


def i16_5():
    """Two throwaway projects through the platform API. What A gets through the module APIs is absent
    from B's database, and A's ids opened under B's pid are 404 on qualification, control-objectives,
    controls, engine and report. The rows of the modules with no JSON create route (a card, an
    assessment, an evaluation, a controls answer) are looked up under B by ids of A that exist: A's card
    version and A's layout."""
    if os.environ.get("VERIFY_SKIP_FUNCTIONAL") == "1":
        say("WARN", "I16.5", "not run (VERIFY_SKIP_FUNCTIONAL=1)")
        return
    token = os.environ.get("VERIFY_ACCESS_TOKEN", "")
    if not token:
        say("FAIL", "I16.5", "not run: VERIFY_ACCESS_TOKEN (a member's access token) is not set")
        return
    made = []
    try:
        tag = uuid.uuid4().hex[:8]
        for label in ("a", "b"):
            status, body = _http("POST", "/api/projects", token, {"name": f"verify-{label}-{tag}"})
            if status != 201:
                say("FAIL", "I16.5", f"POST /projects for project {label.upper()} answered {status}")
                return
            made.append(body)
        a, b = made
        status, version = _http("POST", f"/api/projects/{a['slug']}/system-versions", token,
                                {"name": "Verify", "version": "1", "provider": "verify"})
        if status != 201:
            say("FAIL", "I16.5", f"a card version in A answered {status}")
            return
        va = version["pid"]
        status, layout = _http("POST", f"/report-composer/api/p/{a['pid']}/layouts", token,
                               {"name": "verify", "preset": "empty"})
        la = layout.get("id") if status == 201 and isinstance(layout, dict) else None
        if la is None:
            say("FAIL", "I16.5", f"report: a layout in A answered {status}")
        db_b = "project_" + b["pid"].replace("-", "")
        if one(db_b, "SELECT count(*) FROM project.system WHERE pid = %s", (va,)):
            say("FAIL", "I16.5", f"A's card version {va} is in B's database")
        if la and exists(db_b, "report_composer.layout") and one(
                db_b, "SELECT count(*) FROM report_composer.layout WHERE id = %s::uuid", (la,)):
            say("FAIL", "I16.5", f"A's layout {la} is in B's database")
        bp = b["pid"]
        probes = [
            ("qualification", f"/qualification/p/{bp}/api/system-versions/{va}/ontology.jsonld", None),
            ("control-objectives", f"/control-objectives/p/{bp}/projects/{va}", None),
            ("controls", f"/controls/p/{bp}/submissions/{va}", None),
            ("engine", f"/api/v1/evaluations/{va}", bp),
        ]
        if la:
            probes.append(("report", f"/report-composer/api/p/{bp}/layouts/{la}", None))
            status, _ = _http("GET", f"/report-composer/api/p/{a['pid']}/layouts/{la}", token)
            if status != 200:
                say("FAIL", "I16.5", f"report: A's layout under A answered {status}, not 200")
        for module, path, project in probes:
            status, _ = _http("GET", path, token, project=project)
            if status == 404:
                say("PASS", "I16.5", f"{module}: A's id under B's pid is 404")
            else:
                say("FAIL", "I16.5", f"{module}: A's id under B's pid answered {status}, not 404")
    finally:
        for p in made:
            status, _ = _http("DELETE", f"/api/projects/{p['slug']}", token)
            if status not in (204, 404):
                say("WARN", "I16.5", f"the throwaway project {p['slug']} could not be taken away ({status})")


# I16.6 and I16.7: the consistency check and the connection budget

def i16_6():
    r = subprocess.run([sys.executable, "-m", "db_consistency"], capture_output=True, text=True,
                       env={**os.environ, "NO_COLOR": "1"})
    if r.returncode == 0:
        say("PASS", "I16.6", "db_consistency: every data check passes")
    else:
        for line in r.stdout.splitlines():
            if line.strip().startswith("FAIL"):
                say("FAIL", "I16.6", "db_consistency: " + line.strip()[5:])
        if "I16.6" not in FAILED:
            say("FAIL", "I16.6", f"db_consistency exited {r.returncode}")


def i16_7(project_count):
    per = int(os.environ.get("VERIFY_PER_PROJECT_CONNECTIONS", "11"))
    base = int(os.environ.get("VERIFY_BASE_CONNECTIONS", "20"))
    limit = int(one("platform", "SELECT current_setting('max_connections')::int"))
    budget = project_count * per + base
    if budget > 0.8 * limit:
        text = f"{project_count} projects x {per} + {base} = {budget} connections, above 80% of max_connections {limit}"
        say("WARN", "I16.7", f"{text}: consider PgBouncer (D7)")
    else:
        say("PASS", "I16.7", f"{project_count} projects x {per} + {base} = {budget} connections, under 80% of "
                             f"max_connections {limit}")


def main():
    present = roles()
    dbs = databases()
    project_list = projects()
    own = [db for _p, _s, db in project_list if db in dbs]
    print("I16.1 privileges")
    i16_1_platform(present)
    for db in own:
        i16_1_project(db, present)
    i16_1_inspector(["platform", *own], present)
    print("I16.2 placement")
    i16_2(present)
    if not PRIVILEGES_ONLY:
        print("I16.3 every project has its database, at its heads")
        i16_3(project_list, dbs)
        print("I16.4 configuration")
        i16_4()
        print("I16.5 isolation, functional")
        i16_5()
        print("I16.6 consistency")
        i16_6()
        print("I16.7 connections")
        i16_7(len(project_list))
    print(f"\nfailed checks: {len(FAILED)}")
    return 1 if FAILED else 0


try:
    sys.exit(main())
except psycopg.Error as exc:
    # the server's text may carry a DSN: its first line only, never the connection string
    print(f"  FAIL I16 could not read the cluster: {type(exc).__name__}: "
          f"{str(exc).splitlines()[0] if str(exc) else ''}")
    sys.exit(1)
PY
