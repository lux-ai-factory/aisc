"""scripts/guard-frozen.sh, the guard that the engine and the vendored ontology files stay as upstream
made them, and what it guards.

G1 to G5 and S4.1 to S4.4 are the names of the guard's own checks, as it prints them. A failing check
fails its test with the guard's own reason (MISSING <file>, or the check that differs).
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


# the guard's own hygiene

def test_s0_1_no_container_remains_after_success(tmp_path):
    """A run that succeeds removes its container."""
    r = run([str(GUARD), "--reference-only"], env={**os.environ, "GUARD_OUT": str(tmp_path)}, timeout=600)
    name = container_name(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not container_exists(name)


def test_s0_1_no_container_remains_after_failure(tmp_path):
    """A run that fails after its container started removes it too."""
    r = run([str(GUARD), "--reference-only"],
            env={**os.environ, "GUARD_OUT": str(tmp_path), "GUARD_BACKEND_PY": "/nonexistent/python"}, timeout=600)
    name = container_name(r.stdout)
    assert r.returncode != 0
    assert not container_exists(name)


def test_s0_1_no_container_remains_after_a_signal(tmp_path):
    """SIGTERM while the reference is being built still removes the container."""
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
    """Two runs on an unchanged tree give byte-identical reference dumps."""
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        r = run([str(GUARD), "--reference-only"], env={**os.environ, "GUARD_OUT": str(d)}, timeout=600)
        assert r.returncode == 0, r.stdout + r.stderr
    ra, rb = (a / "engine.reference.sql").read_bytes(), (b / "engine.reference.sql").read_bytes()
    assert len(ra) > 10_000
    assert ra == rb
    assert not (a / "airo.reference.sql").exists(), "G2 is retired: the guard dumps no AIRO schema"


def _code_lines(path):
    """Lines of code, without comments (shell) or docstrings/comments (Python)."""
    text = path.read_text()
    if path.suffix == ".py":
        text = re.sub(r'"""(?:.|\n)*?"""', lambda m: "\n" * m.group(0).count("\n"), text)
        return [(n, l.split("#", 1)[0]) for n, l in enumerate(text.splitlines(), 1)]
    return [(n, "" if l.lstrip().startswith("#") else re.sub(r"\s#\s.*$", "", l))
            for n, l in enumerate(text.splitlines(), 1)]


def test_s0_3_scripts_never_target_the_hosts_5432():
    """5432 appears only as the container side of `-p 127.0.0.1:$PORT:5432` (or in the
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


# G1: the engine schema

G1_PASS = "G1 PASS (engine schema equals Sean's master plus the listed additions)"


def test_s1_1_engine_schema_equals_seans_master(guard_all):
    """G1: the engine migrations at HEAD, applied by migrate_projects in a project database, give
    exactly the schema the engine's origin/master makes, up to the additions the guard lists (and, in
    configurator mode, minus the tables 0019 drops); the "0003 after" order is covered by S4.1, on the
    trees of the shared layout."""
    r, out = guard_all
    lines = verdict(r.stdout, "G1")
    assert lines == [G1_PASS], "\n".join(lines) or r.stdout[-3000:]


def _g1_list():
    """The allowed differences of G1, as written in the script (between its two markers)."""
    text = GUARD.read_text()
    body = text.split("G1_ALLOWED_BEGIN\n", 1)[1].split("G1_ALLOWED_END", 1)[0]
    return [l for l in body.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def test_g1_a_difference_the_list_does_not_name_fails_g1_with_its_name(tmp_path):
    """G1 bites: with two allowed differences left out of the list (an added column and a table
    0019 drops), G1 fails and names each of them."""
    allowed = _g1_list()
    key = lambda l: l.split(" | ", 1)[0].strip()   # a line is `<+|-> <kind> <name>[ | <definition>]`
    left_out = ["+ column aisc_backend_plugin.catalogue_slug", "- table auth_user"]
    assert all(l in map(key, allowed) for l in left_out), allowed
    short = tmp_path / "allowed.txt"
    short.write_text("\n".join(l for l in allowed if key(l) not in left_out) + "\n")
    r = run([str(GUARD), "--only", "G1"], env={**os.environ, "GUARD_OUT": str(tmp_path / "out"),
                                               "GUARD_G1_ALLOWED": str(short)}, timeout=540)
    g1 = verdict(r.stdout, "G1")
    assert r.returncode == 1, r.stdout
    assert len(g1) == 1 and g1[0].startswith("G1 FAIL"), "\n".join(g1)
    for item in left_out:
        assert item in g1[0], (item, g1)


def test_s1_4_backend_part_of_g4_and_g5(guard_all):
    """G4 (backend) and G5 pass."""
    r, out = guard_all
    backend = [l for l in verdict(r.stdout, "G4") if "backend" in l]
    assert backend == [], "\n".join(backend)
    assert verdict(r.stdout, "G5") == ["G5 PASS"], "\n".join(verdict(r.stdout, "G5"))


def test_s1_6_one_ai_system_per_engine_project(guard_all):
    """The candidate engine schema (in a project database) keeps UNIQUE (project_id) on
    engine.aisc_backend_aisystem."""
    r, out = guard_all
    dump = (out / "engine.candidate.sql").read_text()
    assert re.search(r"ALTER TABLE ONLY engine\.aisc_backend_aisystem\s+ADD CONSTRAINT \w+ UNIQUE \(project_id\);",
                     dump), "engine.aisc_backend_aisystem has no UNIQUE (project_id)"


# --- the other guard checks ---------------------------------------------------------------------

# The freeze keeps this repo from diverging from the originals: the authors' AIRO and VAIR files, and
# the engine's upstream code. knowledge_graph and qualification_risk are our own tables, and
# airo_vocab.json is our own list, so G2 is retired and G3 hashes only the two vendored files.

def test_g2_is_retired():
    r = subprocess.run([str(GUARD), "--only", "G2"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    assert "G2 is retired" in r.stderr


def test_g3_hashes_the_authors_files_and_nothing_of_ours(tmp_path):
    r = subprocess.run([str(GUARD), "--only", "G3"], capture_output=True, text=True, timeout=120,
                       env={**os.environ, "GUARD_OUT": str(tmp_path), "GUARD_G3_PYTEST": "0"})
    assert verdict(r.stdout, "G3") == ["G3 PASS (hashes)"], r.stdout + r.stderr
    assert "airo_vocab.json" not in GUARD.read_text().split("g3() {", 1)[1].split("\n}", 1)[0]


def test_g3_still_fails_when_an_authors_file_changes(tmp_path):
    """A copy of the guard over a copy of the two files, one byte of vair.ttl changed."""
    import shutil

    tree = tmp_path / "tree"
    for rel in ("scripts/guard-frozen.sh", "scripts/lib/throwaway-pg.sh", "scripts/guard-frozen-intended.txt",
                "apps/qualification/services/ontology/airo/airo.ttl",
                "apps/qualification/services/ontology/airo/vair.ttl"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tree / rel)
    vair = tree / "apps/qualification/services/ontology/airo/vair.ttl"
    vair.write_text(vair.read_text() + "\n# edited\n")
    r = subprocess.run([str(tree / "scripts/guard-frozen.sh"), "--only", "G3"], capture_output=True, text=True,
                       timeout=120, env={**os.environ, "GUARD_OUT": str(tmp_path / "out"), "GUARD_G3_PYTEST": "0"})
    [line] = verdict(r.stdout, "G3")
    assert line.startswith("G3 FAIL") and "vair.ttl" in line, r.stdout


def test_g3_vendored_airo_vair_files(guard_all):
    """G3: AIRO/VAIR hashes and services/ontology/tests/test_vendored.py."""
    r, out = guard_all
    assert verdict(r.stdout, "G3") == ["G3 PASS (hashes)", "G3 PASS (tests/test_vendored.py)"], \
        "\n".join(verdict(r.stdout, "G3"))


INTENDED = ROOT / "scripts/guard-frozen-intended.txt"
ENGINE_REPOS = ("backend", "eval", "webapp")


def intended(path=INTENDED):
    """(bases, changes): {repo: base commit}, {repo: {path: reason}} from the G4 list."""
    bases, changes = {}, {r: {} for r in ENGINE_REPOS}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        a, b, c = line.split(None, 2)
        if a == "base":
            bases[b] = c.strip()
        else:
            changes[a][b] = c.strip()
    return bases, changes


def test_g4_the_list_names_every_change_of_feat_deployment_modes_with_its_reason():
    """G4: each engine repo is compared with origin/master, the base of feat/deployment-modes; the
    list names exactly the files the branch changes, each with a task and a reason."""
    bases, changes = intended()
    assert sorted(bases) == sorted(ENGINE_REPOS)
    for repo in ENGINE_REPOS:
        git = ["git", "-C", str(ROOT / "apps" / repo)]
        base = subprocess.run(git + ["rev-parse", bases[repo]], capture_output=True, text=True).stdout.strip()
        mb = subprocess.run(git + ["merge-base", "origin/master", "HEAD"], capture_output=True, text=True).stdout.strip()
        assert base and base == mb, f"{repo}: base {bases[repo]} is not origin/master's merge-base with HEAD ({mb[:7]})"
        changed = set(subprocess.run(git + ["diff", "--name-only", base, "HEAD"],
                                     capture_output=True, text=True).stdout.split())
        assert changed - set(changes[repo]) == set(), f"{repo}: changed but not listed"
        assert set(changes[repo]) - changed == set(), f"{repo}: listed but not changed"
        bad = [f for f, why in changes[repo].items() if not re.match(r"T\d+(, T\d+)*: \S", why)]
        assert bad == [], f"{repo}: no task and reason: {bad}"


def test_g4_a_change_the_list_does_not_name_fails_g4(tmp_path):
    """G4 bites: with one file of each engine repo left out of the list, G4 fails naming each."""
    left_out = {"backend": "aisc_backend/routers/plugin.py", "eval": "aisc_eval/deployment.py",
                "webapp": "src/pages/Plugins.tsx"}
    lines = [l for l in INTENDED.read_text().splitlines()
             if not any(l.startswith(f"{r} {f} ") for r, f in left_out.items())]
    short = tmp_path / "intended.txt"
    short.write_text("\n".join(lines) + "\n")
    r = run([str(GUARD), "--only", "G4"], env={**os.environ, "GUARD_OUT": str(tmp_path / "out"),
                                               "GUARD_INTENDED": str(short)}, timeout=300)
    g4 = verdict(r.stdout, "G4")
    assert r.returncode == 1, r.stdout
    assert len(g4) == 3, "\n".join(g4)
    for repo, f in left_out.items():
        hit = [l for l in g4 if f" {repo}: " in l]
        assert len(hit) == 1 and hit[0].split(":")[-1].split() == [f], (repo, f, g4)


def test_g4_passes_on_the_engine_repos_as_listed(tmp_path):
    """G4 alone (no container): the engine repos at their gitlinks, with the list, pass."""
    r = run([str(GUARD), "--only", "G4"], env={**os.environ, "GUARD_OUT": str(tmp_path)}, timeout=300)
    assert verdict(r.stdout, "G4") == ["G4 PASS"], r.stdout


def test_g4_webapp_seans_files_identical_to_origin_master(guard_all):
    """G4 (webapp): every webapp file not on the list equals origin/master."""
    r, out = guard_all
    web = [l for l in verdict(r.stdout, "G4") if "webapp" in l]
    assert web == [], "\n".join(web)


def test_g4_eval_as_listed_plugin_interface_plugin_manager_untouched(guard_all):
    """G4: apps/eval equals origin/master but for the listed files; shared/plugin-interface has no
    new commits; plugin-manager is clean."""
    r, out = guard_all
    other = [l for l in verdict(r.stdout, "G4") if re.search(r"apps/eval|eval:|plugin-interface|plugin-manager", l)]
    assert other == [], "\n".join(other)



def test_g4_plugin_manager_is_merils_staging_commit(tmp_path):
    """G4: shared/plugin-manager is pinned (PM_REF) to Méril's feat/dev-catalogue-staging line (the public
    index without login) as the branch carries it, not to master; the guard records that reference with
    its reason, the submodule sits exactly there, and the guard fails when it is elsewhere."""
    text = GUARD.read_text()
    m = re.search(r"^PM_REF=([0-9a-f]{7,40})\b.*Méril's feat/dev-catalogue-staging", text, re.M)
    assert m, "no PM_REF with its reason"
    head = subprocess.run(["git", "-C", str(ROOT / "shared/plugin-manager"), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head.startswith(m.group(1)), (head, m.group(1))
    merils = subprocess.run(["git", "-C", str(ROOT / "shared/plugin-manager"), "merge-base", "--is-ancestor",
                             "46e1867", head], capture_output=True)
    assert merils.returncode == 0, "the pin no longer holds Méril's staging commit 46e1867"
    assert '"$PM_REF"' in text or "$PM_REF" in text.split("g4()", 1)[1].split("g5()", 1)[0]


# the evaluation stamp stays outside the engine's own files

@pytest.mark.parametrize("path", ["aisc_backend/routers/evaluation.py", "aisc_backend/models/evaluation.py"])
def test_s9_1_seans_evaluation_files_change_only_as_listed_and_never_stamp(path):
    """The system version stamp is set outside the engine's own files. Each file equals
    origin/master or is on the G4 list, and what it adds never sets the stamp."""
    bases, changes = intended()
    r = subprocess.run(["git", "diff", "-U0", bases["backend"], "HEAD", "--", path],
                       cwd=ROOT / "apps/backend", capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    if r.stdout:
        assert path in changes["backend"], f"{path} differs from origin/master and is not listed"
    added = [l[1:] for l in r.stdout.splitlines() if l.startswith("+") and not l.startswith("+++")]
    stamp = [l for l in added if re.search(r"latest_system|system_version|pre_save|\.system_id\s*=", l)]
    assert stamp == [], "\n".join(stamp)


def test_s9_4_g1_equals_seans_master_and_g5_after_the_stamp(guard_all):
    """G1 (origin/master plus the listed additions) and G5 still pass with the stamp in place."""
    r, out = guard_all
    assert verdict(r.stdout, "G1")[:1] == [G1_PASS]
    assert verdict(r.stdout, "G5") == ["G5 PASS"]


# S4: migration orders (guard-frozen.sh --orders)

def test_s4_1_every_order_gives_the_reference_engine_schema(guard_orders):
    """S4.1: every order gives the reference engine schema, with platform 0003 before and after engine 0023."""
    r, out = guard_orders
    assert verdict(r.stdout, "S4.1") == ["S4.1 PASS"], r.stdout[-3000:]


def test_s4_2_core_and_qualification_schema_identical_across_orders(guard_orders):
    """S4.2: core and qualification end with the same schema in every order."""
    r, out = guard_orders
    assert verdict(r.stdout, "S4.2") == ["S4.2 PASS"], r.stdout[-3000:]


def test_s4_3_mcas_card_and_version_survive_every_order(guard_orders):
    """S4.3: card keeps system_id 1e722ea2-..., core.system has it as number 1, 14 answers."""
    r, out = guard_orders
    assert verdict(r.stdout, "S4.3") == ["S4.3 PASS"], r.stdout[-3000:]


def test_s4_4_unowned_core_system_fails_only_at_0003_then_recovers(guard_orders):
    """S4.4: an unowned core.system fails only at platform 0003, then recovers."""
    r, out = guard_orders
    assert verdict(r.stdout, "S4.4") == ["S4.4 PASS"], r.stdout[-3000:]
