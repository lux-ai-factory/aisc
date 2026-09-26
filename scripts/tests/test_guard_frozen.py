"""The guard (03 "Guard spec", WP0) and what it guards (WP1, WP4, WP9 under amendment A1, WP13).

Each test names its rule. A rule whose feature is not built yet fails with the guard's own
reason (MISSING <file>, or the check that differs).
"""

import os
import re
import signal
import subprocess
import time

import pytest

from conftest import GUARD, CHAIN, ROOT, container_exists, container_name, run, verdict

SCRIPTS = [GUARD, CHAIN, ROOT / "scripts/lib/throwaway-pg.sh", ROOT / "scripts/pipeline_chain/throwaway.py",
           ROOT / "scripts/pipeline_chain/test_dashboard_queries.py"]


# --- WP0 ---------------------------------------------------------------------------------------

def test_s0_1_no_container_remains_after_success(tmp_path):
    """S0.1: a run that succeeds removes its container."""
    r = run([str(GUARD), "--reference-only"], env={**os.environ, "GUARD_OUT": str(tmp_path)}, timeout=600)
    name = container_name(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not container_exists(name)


def test_s0_1_no_container_remains_after_failure(tmp_path):
    """S0.1: a run that fails after its container started removes it too."""
    r = run([str(GUARD), "--reference-only"],
            env={**os.environ, "GUARD_OUT": str(tmp_path), "GUARD_BACKEND_PY": "/nonexistent/python"}, timeout=600)
    name = container_name(r.stdout)
    assert r.returncode != 0
    assert not container_exists(name)


def test_s0_1_no_container_remains_after_a_signal(tmp_path):
    """S0.1: SIGTERM while the reference is being built still removes the container."""
    p = subprocess.Popen([str(GUARD), "--reference-only"], cwd=ROOT, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         env={**os.environ, "GUARD_OUT": str(tmp_path)})
    name = None
    deadline = time.time() + 120
    while time.time() < deadline:
        line = p.stdout.readline()
        if line.startswith("container: "):
            name = line.split(": ", 1)[1].strip()
            break
    assert name, "no container line"
    assert container_exists(name)
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=180)
    assert p.returncode != 0
    assert not container_exists(name)


def test_s0_2_two_reference_dumps_are_byte_identical(tmp_path):
    """S0.2: two runs on an unchanged tree give byte-identical reference dumps."""
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        r = run([str(GUARD), "--reference-only"], env={**os.environ, "GUARD_OUT": str(d)}, timeout=600)
        assert r.returncode == 0, r.stdout + r.stderr
    ra, rb = (a / "engine.reference.sql").read_bytes(), (b / "engine.reference.sql").read_bytes()
    assert len(ra) > 10_000
    assert ra == rb
    assert (a / "airo.reference.sql").read_bytes() == (b / "airo.reference.sql").read_bytes()


def _code_lines(path):
    """Lines of code, without comments (shell) or docstrings/comments (Python)."""
    text = path.read_text()
    if path.suffix == ".py":
        text = re.sub(r'"""(?:.|\n)*?"""', lambda m: "\n" * m.group(0).count("\n"), text)
        return [(n, l.split("#", 1)[0]) for n, l in enumerate(text.splitlines(), 1)]
    return [(n, "" if l.lstrip().startswith("#") else re.sub(r"\s#\s.*$", "", l))
            for n, l in enumerate(text.splitlines(), 1)]


def test_s0_3_scripts_never_target_the_hosts_5432():
    """S0.3: 5432 appears only as the container side of `-p 127.0.0.1:$PORT:5432` (or in the
    refusal of port 5432), and every 127.0.0.1 address is on the throwaway port."""
    for path in SCRIPTS:
        for n, code in _code_lines(path):
            for m in re.finditer(r"5432", code):
                before = code[:m.start()]
                assert re.search(r"(\$\{?PORT\}?|\{port\}):$", before) or re.search(r"(!=|=) *\"?$", before), \
                    f"{path.name}:{n}: {code.strip()}"
            for m in re.finditer(r"127\.0\.0\.1:([^/\s\"'@]+)", code):
                assert re.fullmatch(r"(\$\{?PORT\}?|\{(self\.|t\.)?port\}|\$CHAIN_PORT)(:5432)?", m.group(1)), \
                    f"{path.name}:{n}: address not on the throwaway port: {code.strip()}"


# --- WP1: engine undo ---------------------------------------------------------------------------

def test_s1_1_engine_schema_equals_e34fca3(guard_all):
    """S1.1 / G1: the engine migrations at HEAD, applied by migrate_projects in a project database
    (isolation I7.12), give exactly the e34fca3 engine schema up to the two differences of I7.9;
    the "0003 after" order is covered by S4.1, on the pre-isolation trees."""
    r, out = guard_all
    lines = verdict(r.stdout, "G1")
    assert lines == ["G1 PASS (engine schema equals e34fca3)"], "\n".join(lines) or r.stdout[-3000:]


def test_s1_4_backend_part_of_g4_and_g5(guard_all):
    """S1.4: G4 (backend) and G5 pass after WP1."""
    r, out = guard_all
    backend = [l for l in verdict(r.stdout, "G4") if "backend" in l]
    assert backend == [], "\n".join(backend)
    assert verdict(r.stdout, "G5") == ["G5 PASS"], "\n".join(verdict(r.stdout, "G5"))


def test_s1_6_one_ai_system_per_engine_project(guard_all):
    """S1.6: the candidate engine schema (in a project database) keeps UNIQUE (project_id) on
    engine.ai_system."""
    r, out = guard_all
    dump = (out / "engine.candidate.sql").read_text()
    assert re.search(r"ALTER TABLE ONLY engine\.ai_system\s+ADD CONSTRAINT \w+ UNIQUE \(project_id\);", dump), \
        "engine.ai_system has no UNIQUE (project_id)"


# --- the other guard checks ---------------------------------------------------------------------

def test_g2_airo_tables_unchanged(guard_all):
    """G2: qualification.knowledge_graph and qualification_risk unchanged since e112001."""
    r, out = guard_all
    assert verdict(r.stdout, "G2") == ["G2 PASS"], "\n".join(verdict(r.stdout, "G2"))


def test_g3_vendored_airo_vair_files(guard_all):
    """G3: AIRO/VAIR hashes and services/ontology/tests/test_vendored.py."""
    r, out = guard_all
    assert verdict(r.stdout, "G3") == ["G3 PASS (hashes)", "G3 PASS (tests/test_vendored.py)"], \
        "\n".join(verdict(r.stdout, "G3"))


def test_g4_webapp_seans_files_identical_to_429f62c(guard_all):
    """G4 (webapp) / S13.2: Sean's webapp files of 2026-09-23 equal 429f62c."""
    r, out = guard_all
    web = [l for l in verdict(r.stdout, "G4") if "webapp" in l]
    assert web == [], "\n".join(web)


def test_g4_eval_plugin_interface_plugin_manager_untouched(guard_all):
    """G4: apps/eval and shared/plugin-interface have no new commits; plugin-manager is clean."""
    r, out = guard_all
    other = [l for l in verdict(r.stdout, "G4") if re.search(r"apps/eval|plugin-interface|plugin-manager", l)]
    assert other == [], "\n".join(other)


# --- WP9 under amendment A1 ----------------------------------------------------------------------

@pytest.mark.parametrize("path", ["aisc_backend/routers/evaluation.py", "aisc_backend/models/evaluation.py"])
def test_s9_1_seans_evaluation_files_are_byte_identical_to_e34fca3(path):
    """S9.1 as amended by A1: the stamp is set outside Sean's files, which equal e34fca3."""
    r = subprocess.run(["git", "diff", "--stat", "e34fca3", "HEAD", "--", path],
                       cwd=ROOT / "apps/backend", capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "", r.stdout


def test_s9_4_g1_and_g5_after_the_stamp(guard_all):
    """S9.4: G1 and G5 still pass after WP9."""
    r, out = guard_all
    assert verdict(r.stdout, "G1")[:1] == ["G1 PASS (engine schema equals e34fca3)"]
    assert verdict(r.stdout, "G5") == ["G5 PASS"]


# --- WP4: migration orders -----------------------------------------------------------------------

def test_s4_1_every_order_gives_the_reference_engine_schema(guard_orders):
    """S4.1 (and S1.1 with platform 0003 before and after engine 0023)."""
    r, out = guard_orders
    assert verdict(r.stdout, "S4.1") == ["S4.1 PASS"], r.stdout[-3000:]


def test_s4_2_core_and_qualification_schema_identical_across_orders(guard_orders):
    """S4.2"""
    r, out = guard_orders
    assert verdict(r.stdout, "S4.2") == ["S4.2 PASS"], r.stdout[-3000:]


def test_s4_3_mcas_card_and_version_survive_every_order(guard_orders):
    """S4.3: card keeps system_id 1e722ea2-..., core.system has it as number 1, 14 answers."""
    r, out = guard_orders
    assert verdict(r.stdout, "S4.3") == ["S4.3 PASS"], r.stdout[-3000:]


def test_s4_4_unowned_core_system_fails_only_at_0003_then_recovers(guard_orders):
    """S4.4"""
    r, out = guard_orders
    assert verdict(r.stdout, "S4.4") == ["S4.4 PASS"], r.stdout[-3000:]
