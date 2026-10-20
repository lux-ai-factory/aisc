"""A check of the running stack must not pass because its probe itself failed.

- verify-db-access.sh: a "cannot ..." check passes only when PostgreSQL refuses for a privilege
  (permission denied), not for any error. A missing probe database, a failed login or a missing table
  is a FAIL.
- verify-rbac.sh section 6: when the superset database cannot be read, "only nobody can reach SQL Lab"
  is not a PASS.
- verify-sso.sh: when the engine's bundle cannot be read, "its launcher URL is substituted" is not a
  PASS.

Each runs with a fake `docker` on PATH; nothing reaches the stack.
"""
import os
import re
import subprocess

from conftest import ROOT

# psql as the scripts call it: the connection string names the role and the database. The probe project
# database could not be made, so connecting to it fails; a module's write in `platform` is refused for a
# privilege; everything else succeeds.
FAKE_PSQL_DOCKER = r"""#!/usr/bin/env bash
conn=""; sql=""; prev=""
for a in "$@"; do
  case "$a" in postgresql://*) conn=$a ;; esac
  [ "$prev" = "-c" ] && sql=$a
  prev=$a
done
user=${conn#postgresql://}; user=${user%%:*}; db=${conn##*/}
case "$sql" in *"create database \"project_"*) echo "ERROR:  could not create" >&2; exit 1 ;; esac
case "$db" in project_*)
  echo "psql: error: connection to server failed: FATAL:  database \"$db\" does not exist" >&2; exit 2 ;;
esac
[ "$user" = platform_rw ] && exit 0
case "$sql" in select*) exit 0 ;; esac
echo "ERROR:  permission denied for table project" >&2; exit 1
"""


def _fake_docker(tmp_path, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(body)
    (bin_dir / "docker").chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def test_db_access_a_denial_counts_only_when_postgres_refuses_for_a_privilege(tmp_path):
    env = _fake_docker(tmp_path, FAKE_PSQL_DOCKER)
    r = subprocess.run(["bash", str(ROOT / "scripts/verify-db-access.sh")], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    lines = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout).splitlines()
    in_probe_db = [line for line in lines if "cannot read the LLM keys" in line or "cannot write project.system" in line]
    assert in_probe_db and all("FAIL" in line for line in in_probe_db), in_probe_db
    refused = [line for line in lines if "cannot write core.project" in line]
    assert refused and all("PASS" in line for line in refused), refused
    assert r.returncode != 0


def _snippet(path, start, end):
    text = path.read_text()
    i = text.index(start)
    return text[i:text.index(end, i)]


def _run_snippet(snippet, env):
    harness = "set -uo pipefail\nok(){ printf 'OK %s\\n' \"$1\"; }\nno(){ printf 'NO %s\\n' \"$1\"; }\n" + snippet
    r = subprocess.run(["bash", "-c", harness], env=env, capture_output=True, text=True, timeout=30)
    return r.stdout


def test_rbac_an_unreadable_superset_database_is_not_a_pass(tmp_path):
    env = _fake_docker(tmp_path, "#!/bin/sh\necho 'FATAL:  database \"superset\" does not exist' >&2\nexit 2\n")
    snippet = _snippet(ROOT / "scripts/verify-rbac.sh", 'echo "6. the dashboard', "# Without this the count")
    out = _run_snippet(snippet, env)
    assert "NO" in out and "OK" not in out, out


def test_rbac_a_readable_superset_database_still_passes(tmp_path):
    env = _fake_docker(tmp_path, "#!/bin/sh\nprintf 'Admin\\n'\n")
    snippet = _snippet(ROOT / "scripts/verify-rbac.sh", 'echo "6. the dashboard', "# Without this the count")
    out = _run_snippet(snippet, env)
    assert "OK only Admin" in out and "NO" not in out, out


def test_sso_an_unreadable_bundle_is_not_a_pass(tmp_path):
    env = _fake_docker(tmp_path, "#!/bin/sh\necho 'Error: No such container: aisc-webapp' >&2\nexit 1\n")
    snippet = _snippet(ROOT / "scripts/verify-sso.sh", "bundle=$(docker exec aisc-webapp", 'echo "2d.')
    out = _run_snippet(snippet, env)
    assert "NO" in out and "OK" not in out, out


def test_sso_a_good_bundle_still_passes(tmp_path):
    env = _fake_docker(tmp_path, "#!/bin/sh\nprintf 'var a=\"Back to the AI Assessment Sandbox\";var u=\"http://launcher/evidence.html?project=\";'\n")
    snippet = _snippet(ROOT / "scripts/verify-sso.sh", "bundle=$(docker exec aisc-webapp", 'echo "2d.')
    out = _run_snippet(snippet, env)
    assert "NO" not in out and out.count("OK") == 2, out


def _audit_snippet(code, body):
    """The audit check of verify-rbac.sh, with the gateway's answer given."""
    fake = f"through_gateway(){{ echo {code}; }}\nthrough_gateway_body(){{ printf '%s' '{body}'; }}\n"
    return fake + _snippet(ROOT / "scripts/verify-rbac.sh", "AUDIT_CODE=$(through_gateway", 'is "a call that names no project')


def test_rbac_a_failing_engine_audit_log_is_a_fail_that_names_the_cause_and_the_remedy():
    """The engine's audit log fails when immudb is down or refuses the engine's account (its clerk logs in
    again by itself after an ended login). The check stays a FAIL and says where to look."""
    out = _run_snippet(_audit_snippet(500, "{}"), {**os.environ, "ADMIN_SESSION": "a", "MINE": "p", "ENG": "/api/v1"})
    assert "NO " in out and "OK " not in out, out
    assert "verify-immudb.sh" in out and "immudb" in out and "log" in out, out


def test_rbac_a_verified_engine_audit_log_still_passes():
    out = _run_snippet(_audit_snippet(200, '{"verified": true}'),
                       {**os.environ, "ADMIN_SESSION": "a", "MINE": "p", "ENG": "/api/v1"})
    assert "OK " in out and "NO " not in out, out
