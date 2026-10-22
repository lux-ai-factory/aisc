"""scripts/guard-frozen.sh, the guard that the engine and the vendored ontology files stay as upstream
made them, and what it guards.

G1 to G5 and orders-engine, orders-schemas, orders-card and orders-ownership are the names of the guard's
own checks, as it prints them and as its header explains them. A failing check
fails its test with the guard's own reason (MISSING <file>, or the check that differs).
"""

import os
import re
import signal
import subprocess
import time

import pytest

from conftest import GUARD, CHAIN, ROOT, container_exists, container_name, needs_guard_history, run, verdict

SCRIPTS = [GUARD, CHAIN, ROOT / "scripts/lib/throwaway-pg.sh", ROOT / "scripts/pipeline_chain/throwaway.py",
           ROOT / "scripts/pipeline_chain/test_dashboard_queries.py"]


# the guard's own hygiene

@needs_guard_history()
def test_no_container_remains_after_success(tmp_path):
    """A run that succeeds removes its container."""
    r = run([str(GUARD), "--reference-only"], env={**os.environ, "GUARD_OUT": str(tmp_path)}, timeout=600)
    name = container_name(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not container_exists(name)


def test_no_container_remains_after_failure(tmp_path):
    """A run that fails after its container started removes it too."""
    r = run([str(GUARD), "--reference-only"],
            env={**os.environ, "GUARD_OUT": str(tmp_path), "GUARD_BACKEND_PY": "/nonexistent/python"}, timeout=600)
    name = container_name(r.stdout)
    assert r.returncode != 0
    assert not container_exists(name)


def test_no_container_remains_after_a_signal(tmp_path):
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


@needs_guard_history()
def test_two_reference_dumps_are_byte_identical(tmp_path):
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
        return [(n, line.split("#", 1)[0]) for n, line in enumerate(text.splitlines(), 1)]
    return [(n, "" if line.lstrip().startswith("#") else re.sub(r"\s#\s.*$", "", line))
            for n, line in enumerate(text.splitlines(), 1)]


def test_scripts_never_target_the_hosts_5432():
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


# G1 and G5 are retired: the engine is ours to change

@pytest.mark.parametrize("check", ["G1", "G5"])
def test_the_retired_checks_g1_and_g5_are_refused(check, tmp_path):
    r = run([str(GUARD), "--only", check], env={**os.environ, "GUARD_OUT": str(tmp_path)}, timeout=60)
    assert r.returncode == 2 and "retired" in r.stderr, (r.stdout, r.stderr)


def test_the_default_run_checks_g3_and_g4_only(guard_all):
    r, out = guard_all
    assert verdict(r.stdout, "G1") == [] and verdict(r.stdout, "G5") == [], r.stdout[-2000:]


# --- the other guard checks ---------------------------------------------------------------------

# The freeze keeps this repo from diverging from the originals: the authors' AIRO and VAIR files, and
# the engine's upstream code. knowledge_graph and qualification_risk are our own tables, and
# airo_vocab.json is our own list, so G2 is retired and G3 hashes only the two vendored files.

def test_the_ontology_check_g3_hashes_the_authors_files_and_nothing_of_ours(tmp_path):
    r = subprocess.run([str(GUARD), "--only", "G3"], capture_output=True, text=True, timeout=120,
                       env={**os.environ, "GUARD_OUT": str(tmp_path), "GUARD_G3_PYTEST": "0"})
    assert verdict(r.stdout, "G3") == ["G3 PASS (hashes)"], r.stdout + r.stderr
    assert "airo_vocab.json" not in GUARD.read_text().split("g3() {", 1)[1].split("\n}", 1)[0]


def test_the_ontology_check_g3_still_fails_when_an_authors_file_changes(tmp_path):
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


def test_the_ontology_check_g3_passes_on_the_vendored_airo_vair_files(guard_all):
    """G3: AIRO/VAIR hashes and the ontology's own check that the vendored files are upstream
    (test_vair_terms.py::TestTheVendoredFilesAreUpstream)."""
    r, out = guard_all
    assert verdict(r.stdout, "G3") == ["G3 PASS (hashes)", "G3 PASS (the vendored files are upstream: test_vair_terms.py)"], \
        "\n".join(verdict(r.stdout, "G3"))


INTENDED = ROOT / "scripts/guard-frozen-intended.txt"
#: the engine repos G4 still holds to upstream: only the webapp (backend and eval are ours to change)
ENGINE_REPOS = ("webapp",)


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


def labels(path=INTENDED):
    """The labels the G4 list's header defines, one per `#   <label>  <meaning>` line."""
    return {m.group(1) for m in re.finditer(r"^#   ([a-z]+)  +\S", path.read_text(), re.M)}


def test_the_upstream_check_g4_lists_every_change_of_feat_deployment_modes_with_its_reason():
    """G4: each engine repo is compared with origin/master, the base of feat/deployment-modes; the
    list names exactly the files the branch changes, each with an area its header defines and a reason."""
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
        # the labels the list's header defines (`#   <label>  <meaning>`)
        bad = [f for f, why in changes[repo].items()
               if not re.match(r"[a-z]+(, [a-z]+)*: \S", why)
               or not set(why.split(":", 1)[0].split(", ")) <= labels()]
        assert bad == [], f"{repo}: no area the header defines, or no reason: {bad}"


def test_the_upstream_check_g4_fails_on_a_change_its_list_does_not_name(tmp_path):
    """G4 bites: with a webapp file left out of the list, G4 fails naming it."""
    left_out = {"webapp": "src/pages/Plugins.tsx"}
    lines = [line for line in INTENDED.read_text().splitlines()
             if not any(line.startswith(f"{r} {f} ") for r, f in left_out.items())]
    short = tmp_path / "intended.txt"
    short.write_text("\n".join(lines) + "\n")
    r = run([str(GUARD), "--only", "G4"], env={**os.environ, "GUARD_OUT": str(tmp_path / "out"),
                                               "GUARD_INTENDED": str(short)}, timeout=300)
    g4 = verdict(r.stdout, "G4")
    assert r.returncode == 1, r.stdout
    assert len(g4) == 1, "\n".join(g4)
    for repo, f in left_out.items():
        hit = [line for line in g4 if f" {repo}: " in line]
        assert len(hit) == 1 and hit[0].split(":")[-1].split() == [f], (repo, f, g4)


def test_the_upstream_check_g4_passes_on_the_engine_repos_as_listed(tmp_path):
    """G4 alone (no container): the webapp at its gitlink, with the list, passes."""
    r = run([str(GUARD), "--only", "G4"], env={**os.environ, "GUARD_OUT": str(tmp_path)}, timeout=300)
    assert verdict(r.stdout, "G4") == ["G4 PASS"], r.stdout


def test_the_upstream_check_g4_leaves_the_backend_and_eval_alone(tmp_path):
    """The engine's backend and worker are ours to change: a change in them is not G4's business."""
    r = run([str(GUARD), "--only", "G4"], env={**os.environ, "GUARD_OUT": str(tmp_path)}, timeout=300)
    assert not [line for line in verdict(r.stdout, "G4") if re.search(r"\b(backend|eval):", line)], r.stdout


def test_the_upstream_check_g4_finds_the_webapp_upstream_files_identical_to_origin_master(guard_all):
    """G4 (webapp): every webapp file not on the list equals origin/master."""
    r, out = guard_all
    web = [line for line in verdict(r.stdout, "G4") if "webapp" in line]
    assert web == [], "\n".join(web)


def test_the_upstream_check_g4_finds_plugin_interface_and_plugin_manager_untouched(guard_all):
    """G4: shared/plugin-interface has no new commits; plugin-manager is clean."""
    r, out = guard_all
    other = [line for line in verdict(r.stdout, "G4") if re.search(r"plugin-interface|plugin-manager", line)]
    assert other == [], "\n".join(other)



def test_the_upstream_check_g4_holds_plugin_manager_on_the_staging_commit(tmp_path):
    """G4: shared/plugin-manager is pinned (PM_REF) to its maintainers' feat/dev-catalogue-staging line (the public
    index without login) as the branch carries it, not to master; the guard records that reference with
    its reason, the submodule sits exactly there, and the guard fails when it is elsewhere."""
    text = GUARD.read_text()
    m = re.search(r"^PM_REF=([0-9a-f]{7,40})\b.*its maintainers' feat/dev-catalogue-staging", text, re.M)
    assert m, "no PM_REF with its reason"
    head = subprocess.run(["git", "-C", str(ROOT / "shared/plugin-manager"), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head.startswith(m.group(1)), (head, m.group(1))
    staging = subprocess.run(["git", "-C", str(ROOT / "shared/plugin-manager"), "merge-base", "--is-ancestor",
                             "46e1867", head], capture_output=True)
    assert staging.returncode == 0, "the pin no longer holds the staging commit 46e1867"
    assert '"$PM_REF"' in text or "$PM_REF" in text.split("g4()", 1)[1].split("g5()", 1)[0]


# migration orders (guard-frozen.sh --orders)

def test_orders_engine_every_order_gives_the_reference_engine_schema(guard_orders):
    """orders-engine: every order gives the reference engine schema, with platform 0003 before and after engine 0023."""
    r, out = guard_orders
    assert verdict(r.stdout, "orders-engine") == ["orders-engine PASS"], r.stdout[-3000:]


def test_orders_schemas_core_and_qualification_schema_identical_across_orders(guard_orders):
    """orders-schemas: core and qualification end with the same schema in every order."""
    r, out = guard_orders
    assert verdict(r.stdout, "orders-schemas") == ["orders-schemas PASS"], r.stdout[-3000:]


def test_orders_card_mcas_card_and_version_survive_every_order(guard_orders):
    """orders-card: the MCAS card keeps system_id 1e722ea2-..., core.system has it as number 1, 14 answers."""
    r, out = guard_orders
    assert verdict(r.stdout, "orders-card") == ["orders-card PASS"], r.stdout[-3000:]


def test_orders_ownership_unowned_core_system_fails_only_at_0003_then_recovers(guard_orders):
    """orders-ownership: an unowned core.system fails only at platform 0003, then recovers."""
    r, out = guard_orders
    assert verdict(r.stdout, "orders-ownership") == ["orders-ownership PASS"], r.stdout[-3000:]


def _pi_clone(tmp_path):
    """A scratch clone of shared/plugin-interface, so G4 can be pointed at a moved or dirty copy without
    touching the real submodule."""
    ref = re.search(r"^PI_REF=([0-9a-f]{7,40})", GUARD.read_text(), re.M).group(1)
    clone = tmp_path / "plugin-interface"
    subprocess.run(["git", "clone", "-q", str(ROOT / "shared/plugin-interface"), str(clone)], check=True)
    return clone, ref


def _g4_pi_lines(tmp_path, clone):
    r = run([str(GUARD), "--only", "G4"], env={**os.environ, "GUARD_OUT": str(tmp_path / "out"),
                                               "GUARD_PI_DIR": str(clone)}, timeout=300)
    return [line for line in verdict(r.stdout, "G4") if "plugin-interface" in line]


def test_the_upstream_check_g4_fails_on_plugin_interface_moved_back_before_its_pin(tmp_path):
    """PI_REF..HEAD is empty when HEAD is an ancestor of PI_REF, so a checkout moved back to
    before the pinned commit (its SSRF guard) passed G4."""
    clone, ref = _pi_clone(tmp_path)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", f"{ref}~1"], check=True)
    lines = _g4_pi_lines(tmp_path, clone)
    assert any(f"is not at {ref}" in line for line in lines), lines


def test_the_upstream_check_g4_fails_on_plugin_interface_with_uncommitted_changes(tmp_path):
    clone, ref = _pi_clone(tmp_path)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", ref], check=True)
    (clone / "README.md").write_text((clone / "README.md").read_text() + "\nchanged\n")
    lines = _g4_pi_lines(tmp_path, clone)
    assert any("is not clean" in line for line in lines), lines


def test_the_upstream_check_g4_passes_plugin_interface_at_its_pin_and_clean(tmp_path):
    clone, ref = _pi_clone(tmp_path)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", ref], check=True)
    assert _g4_pi_lines(tmp_path, clone) == []
