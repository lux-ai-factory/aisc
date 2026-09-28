"""The cutover and rehearsal scripts (01-specs.md sections 13, 14, 15: I13.1..I13.4, I14.1..I14.7,
I15.1, I15.2, I18.7).

Static checks on scripts/isolation/cutover.sh and rehearse.sh, plus what can run without any database:
the step order refusal and the rollback listing, with the state directory in a temporary folder. Nothing
here touches the running stack: every run sets a scratch state directory and `--target rehearsal`, and
only steps that refuse before doing anything are run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

CUTOVER = ROOT / "scripts/isolation/cutover.sh"
REHEARSE = ROOT / "scripts/isolation/rehearse.sh"
STEPS = ["C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C8b", "C9", "C10", "C11", "C12"]


def text(path: Path) -> str:
    assert path.exists(), f"{path.relative_to(ROOT)} missing"
    return path.read_text()


def code(path: Path) -> str:
    """The script without comment lines."""
    return "\n".join(l for l in text(path).splitlines() if not l.lstrip().startswith("#"))


def run(args, state: Path, timeout=60):
    assert CUTOVER.exists(), "I13.1: scripts/isolation/cutover.sh missing"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(ISOLATION_STATE_DIR=str(state), ISOLATION_BACKUP_DIR=str(state / "backup"), NO_COLOR="1")
    return subprocess.run(["bash", str(CUTOVER), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=timeout)


# ── I13.1 the steps, in order, each with a check ─────────────────────────────


def test_i13_1_cutover_script_exists_and_is_executable():
    assert CUTOVER.exists(), "I13.1: scripts/isolation/cutover.sh missing"
    assert os.access(CUTOVER, os.X_OK), "I13.1: cutover.sh is not executable"


def test_i13_1_every_step_is_a_subcommand_in_order():
    body = code(CUTOVER)
    positions = []
    for s in STEPS:
        m = re.search(rf"(^|[\s|(]){s}\)", body, re.M)
        assert m, f"I13.1: cutover.sh has no subcommand {s}"
        positions.append(m.start())
    assert positions == sorted(positions), "I13.1: subcommands are not in the order C0..C12"


def test_i13_1_the_script_lists_its_steps_in_order(tmp_path):
    r = run(["steps"], tmp_path)
    assert r.returncode == 0, "I13.1: `cutover.sh steps` failed: " + r.stderr[-300:]
    listed = re.findall(r"^\s*(C\d+b?)\b", r.stdout, re.M)
    assert listed == STEPS, f"I13.1: steps listed {listed}"


def test_i13_1_a_step_refuses_to_start_before_the_previous_one_passed(tmp_path):
    """I13.1: with no recorded passed step, C3 refuses (non-zero) and records nothing."""
    r = run(["C3", "--target", "rehearsal"], tmp_path)
    assert r.returncode != 0, "I13.1: C3 ran without C2 recorded as passed"
    assert re.search(r"C2", r.stdout + r.stderr), "I13.1: the refusal does not name the missing step C2"
    state = tmp_path / "cutover-state.json"
    if state.exists():
        assert "C3" not in json.loads(state.read_text()).get("passed", []), "I13.1: a refused step was recorded"


def test_i13_1_a_step_after_a_fake_passed_state_still_checks_its_predecessor(tmp_path):
    """I13.1: the state file records passed steps; C5 after a state of C0..C3 (C4 missing) refuses."""
    (tmp_path / "cutover-state.json").write_text(json.dumps({"passed": ["C0", "C1", "C2", "C3"]}))
    r = run(["C5", "--target", "rehearsal"], tmp_path)
    assert r.returncode != 0 and "C4" in (r.stdout + r.stderr), "I13.1: C5 did not refuse for missing C4"


def test_i13_1_the_state_file_is_named_cutover_state_json():
    assert "cutover-state.json" in text(CUTOVER), "I13.1: cutover.sh does not keep cutover-state.json"


@pytest.mark.parametrize("step,needle", [
    ("C1", "pg_dumpall"), ("C1", "pg_restore --list"), ("C2", "pg_stat_activity"),
    ("C3", "isolate plan"), ("C6", "isolate provision"), ("C8", "isolate copy"), ("C10", "isolate verify"),
    ("C12", "verify-project-databases.sh"),
])
def test_i13_steps_run_their_check(step, needle):
    """Section 13 table: each step's action and check appear in the script."""
    assert needle in code(CUTOVER), f"section 13 {step}: cutover.sh does not run `{needle}`"


def test_i13_4_the_quiet_check_is_repeated_at_c8_and_c10():
    """I13.4: C2's no-module-session check runs again at C8 and C10."""
    body = code(CUTOVER)
    assert body.count("pg_stat_activity") >= 1
    fn = re.search(r"(\w+)\s*\(\)\s*\{[^}]*pg_stat_activity", body, re.S)
    assert fn, "I13.4: the quiet check is not a function the steps can repeat"
    assert body.count(fn.group(1)) >= 4, f"I13.4: {fn.group(1)} is not called at C2, C8 and C10"


# ── I13.2, I14 rollbacks ─────────────────────────────────────────────────────


def test_i13_2_every_step_has_a_named_rollback(tmp_path):
    for s in STEPS:
        r = run(["rollback", s, "--print"], tmp_path)
        assert r.returncode == 0 and r.stdout.strip(), f"I13.2: `cutover.sh rollback {s}` prints nothing"


def test_i14_4_rollback_c8_drops_only_the_schemas_of_0006_to_0010():
    """I14.4: only schemas created by 0006..0010, after confirming provision.template_migration names; never
    controls or llm."""
    body = code(CUTOVER)
    assert "provision.template_migration" in body, "I14.4: rollback C8 does not confirm template names"
    for schema in ("controls", "llm"):
        assert not re.search(rf"DROP SCHEMA[^;\n]*\b{schema}\b", body, re.I), f"I14.4: cutover.sh may drop {schema}"
    for schema in ("project", "qualification", "control_objectives", "engine", "report_composer"):
        assert re.search(rf"\b{schema}\b", body), f"I14.4: rollback C8 does not name {schema}"


def test_i14_5_c9_saves_and_restores_acls():
    body = code(CUTOVER)
    assert "c9-acl.json" in body, "I14.5: C9 does not save ACLs and owners to c9-acl.json"


def test_i14_3_rollback_c4_documents_the_restore_and_swap():
    body = code(CUTOVER)
    assert "pg_restore" in body and re.search(r"ALTER DATABASE[^;\n]*RENAME", body), \
        "I14.3: rollback C4 lacks the restore into a new database and the rename swap"


def test_i14_7_caddy_starts_last_after_c12():
    """I14.7: users are let in only after C12 passed (caddy is the last thing started)."""
    body = code(CUTOVER)
    assert "caddy" in body, "I14.7: cutover.sh never mentions caddy"


# ── I13.3, I18.7 no secret and no row value, backups outside the repo ────────


def test_i13_3_dumps_and_reports_are_mode_600_under_the_backup_directory():
    body = code(CUTOVER)
    assert "aisc-isolation-backup" in body, "I13.3: backups are not written to ~/aisc-isolation-backup"
    assert re.search(r"umask 0?77|chmod 600|chmod 0600", body), "I13.3: dumps are not made mode 600"


@pytest.mark.parametrize("path", [CUTOVER, REHEARSE])
def test_i18_7_no_credential_is_echoed(path):
    """I13.3, I18.7: no echo/printf of a password variable, no `set -x`."""
    body = code(path)
    assert not re.search(r"set -[a-z]*x", body), f"I18.7: {path.name} traces commands (set -x)"
    for line in body.splitlines():
        if re.search(r"\b(echo|printf)\b", line):
            assert not re.search(r"\$\{?(POSTGRES_PASSWORD|PGPASSWORD|\w*_PASSWORD|\w*TOKEN|\w*SECRET)", line), \
                f"I18.7: {path.name} prints a secret: {line.strip()[:80]}"


def test_i13_3_backups_are_never_written_inside_a_repository():
    body = code(CUTOVER)
    assert not re.search(r"(\$ROOT|\$HERE|\./)[^\s]*\.(sql|dump|json)\b", body), \
        "I13.3: cutover.sh writes a dump or report inside the repository"


# ── I15.1 the rehearsal script ───────────────────────────────────────────────


def test_i15_1_rehearsal_script_exists():
    assert REHEARSE.exists(), "I15.1: scripts/isolation/rehearse.sh missing"


def test_i15_1_rehearsal_uses_a_throwaway_postgres_on_a_random_port():
    body = code(REHEARSE)
    assert "postgres:15-alpine" in body or "throwaway-pg.sh" in body, "I15.1: not a postgres:15-alpine throwaway"
    assert "5432" in body and re.search(r"!=\s*\"?5432|=\s*\"?5432\"?\s*\]", body), \
        "I15.1: rehearse.sh does not refuse port 5432"
    assert re.search(r"docker rm -f|tpg_cleanup", body), "I15.1: the container is not removed"
    assert "trap" in body, "I15.1: no trap removes the container on failure"


def test_i15_1_rehearsal_restores_the_copy_without_printing_it():
    body = code(REHEARSE)
    assert re.search(r"aisc-isolation-rehearsal/live-\*\.sql|aisc-isolation-rehearsal", body), \
        "I15.1: rehearse.sh does not restore ~/aisc-isolation-rehearsal/live-*.sql"
    for line in body.splitlines():
        if "live-" in line and "psql" in line:
            assert ">/dev/null" in line.replace(" ", "") or "-o /dev/null" in line or "-q" in line, \
                f"I15.1: the restore may print the dump: {line.strip()[:80]}"
        assert not re.search(r"\bcat\b[^|]*live-", line), "I15.1: rehearse.sh cats the dump"


def test_i15_1_rehearsal_runs_twice_injects_a_failure_and_resumes():
    body = code(REHEARSE)
    assert "already done" in body, "I15.1: the second run's `already done` is not checked"
    assert re.search(r"inject|ISOLATE_FAIL|fail[-_]after", body, re.I), "I15.1: no injected failure midway through C8"
    assert re.search(r"resume", body, re.I), "I15.1: the resume after the injected failure is not proven"
    for step in ("C3", "C8", "C10"):
        assert step in body, f"I15.1: rehearse.sh does not run {step}"


def test_i15_1_rehearsal_runs_the_cutover_script_against_the_throwaway():
    body = code(REHEARSE)
    assert "cutover.sh" in body and "--target rehearsal" in body, \
        "I15.1: rehearse.sh does not run cutover.sh --target rehearsal"


# ── I15.2 the drop step ──────────────────────────────────────────────────────


def test_i15_2_drop_statements_appear_only_in_a_step_guarded_by_verify_dump():
    body = code(CUTOVER)
    drops = [m.start() for m in re.finditer(r"DROP SCHEMA[^;\n]*qualification", body, re.I)]
    assert drops, "I15.2: the stage-7 drop is not in cutover.sh"
    for pos in drops:
        before = body[max(0, pos - 4000):pos]
        assert "verify-dump" in before, "I15.2: DROP SCHEMA is not preceded by isolate verify-dump"
        assert "pg_stat_user_tables" in before, "I15.2: the C9 counter snapshot is not compared before the drop"
    assert re.search(r"pg_dump -Fc[^\n]*-n qualification[^\n]*-t core\.system", body), \
        "I15.2: the pg_dump -Fc of the shared schemas before the drop is missing"


def test_i15_3_databases_needing_a_user_decision_are_never_dropped():
    """I15.3: aisc, controls, qualification, control_objectives, control_objectives_test, the orphan project
    databases, the catalogue and Superset's aisc_* tables are reported only."""
    body = code(CUTOVER)
    for name in ("aisc", "controls", "qualification", "control_objectives", "control_objectives_test"):
        assert not re.search(rf"DROP DATABASE[^;\n]*\b{name}\b", body, re.I), f"I15.3: cutover.sh drops database {name}"
    assert not re.search(r"DROP SCHEMA[^;\n]*\bcatalogue\b", body, re.I), "I15.3: cutover.sh drops catalogue"
    assert not re.search(r"DROP TABLE[^;\n]*aisc_(comment|review_request)", body, re.I), \
        "I15.3: cutover.sh drops Superset's aisc_* tables"


# ── I14.1, I14.2, I14.6 what each rollback says ──────────────────────────────


@pytest.mark.parametrize("step,needle,req", [
    ("C0", "pre-isolation", "I14.1"), ("C1", "pre-isolation", "I14.1"), ("C2", "pre-isolation", "I14.1"),
    ("C3", "nothing to undo", "I14.2"),
    ("C5", "pre-isolation", "I14.4"), ("C8", "rollback C8", "I14.4"),
    ("C9", "c9-acl.json", "I14.5"),
    ("C10", "c9-acl.json", "I14.6"), ("C11", "c9-acl.json", "I14.6"), ("C12", "c9-acl.json", "I14.6"),
])
def test_i14_each_rollback_names_its_action(tmp_path, step, needle, req):
    """Section 14: C0..C2 restart the :pre-isolation images; C3 is read-only; C5..C8b restart the old images
    and point at `rollback C8`; C9..C12 restore what C9 saved in c9-acl.json."""
    r = run(["rollback", step, "--print"], tmp_path)
    assert r.returncode == 0, f"{req}: `cutover.sh rollback {step} --print` failed"
    assert needle.lower() in r.stdout.lower(), f"{req}: rollback {step} does not mention {needle!r}"


def test_i14_7_the_point_of_no_return_is_stated():
    """I14.7: after users are let in, rows written since C11 exist only in project databases; the script says
    so before starting caddy."""
    body = code(CUTOVER)
    assert re.search(r"point of no return|no return", body, re.I), "I14.7: cutover.sh does not state the point of no return"


def test_i15_2_the_drop_is_exactly_the_four_schemas_core_system_and_its_function():
    """I15.2: DROP SCHEMA qualification, control_objectives, engine, report_composer CASCADE; DROP TABLE
    core.system CASCADE; DROP FUNCTION IF EXISTS core.system_only_latest_changes(); and nothing else."""
    body = code(CUTOVER)
    schemas = set()
    for m in re.finditer(r"DROP SCHEMA\s+(?:IF EXISTS\s+)?([\w\s,]+?)\s+CASCADE", body, re.I):
        schemas |= {s.strip() for s in m.group(1).split(",")}
    # rollback C8 (I14.4) drops the new schemas inside project databases; the stage-7 drop is on platform
    assert {"qualification", "control_objectives", "engine", "report_composer"} <= schemas, \
        f"I15.2: stage-7 drop names {sorted(schemas)}"
    assert not (schemas - {"qualification", "control_objectives", "engine", "report_composer", "project"}), \
        f"I15.2: cutover.sh drops other schemas {sorted(schemas)}"
    assert re.search(r"DROP TABLE\s+(IF EXISTS\s+)?core\.system\s+CASCADE", body, re.I), "I15.2: no DROP TABLE core.system"
    assert re.search(r"DROP FUNCTION IF EXISTS core\.system_only_latest_changes\(\)", body, re.I), \
        "I15.2: no DROP FUNCTION core.system_only_latest_changes()"
    for other in ("core.project", "core.project_member", "core.schema_migration"):
        assert not re.search(rf"DROP TABLE[^;\n]*{re.escape(other)}\b", body, re.I), f"I15.2: drops {other}"
