"""Code, comments, docstrings and text files explain why the code is as it is, not the history of how it
was decided: no date tag on an explanation, no internal plan, ruling, task, review or workshop named.
Git history records when and where something was decided; the code reads as if written for a stranger.
A test, likewise, is named for what it checks, not for the plan item it came from (test_tg6_..., it("I16.1")).

Scanned: every tracked text file of the root repo and of the submodules below that are ours (when checked
out). Left out: changelogs, lock files, SQL seeds,
fixtures and the report tests' golden files, which hold data. A date that is data is not history: a
timestamp (a date followed by a time), a date inside a one-line string literal of a code line, a date
given as a value (`=2026-09-10`). Each finding is named as file:line.
"""
import re
import subprocess

import pytest

from conftest import ROOT

#: the submodules held to the same rule
SUBMODULES = ("apps/qualification", "apps/controls", "apps/control-objectives", "apps/backend", "apps/eval",
              "apps/report-generator", "shared/report-plugin-interface", "apps/results-dashboard",
              "apps/catalogue", "apps/webapp", "shared/plugin-interface", "shared/plugin-manager")

DATE = r"\b20\d{2}-\d{2}-\d{2}\b"
#: what reads as history: a dated explanation or a reference to an internal plan, ruling, task or meeting
HISTORY = re.compile("|".join([
    r"\(20\d{2}-\d{2}-\d{2}\)",                                  # a date tag: (2026-10-04)
    r"\b(review|decisions|workshop|pass|plan) 20\d{2}-\d{2}-\d{2}",  # review 2026-10-05
    r"\bRuling \d+",
    r"(?<![\w{}])T\d+(, T\d+)*: ",                                # task labels: T7, T8: (not T00:00)
    r"\badapt plan",
    r"pipeline-20\d{2}",
    DATE,
    r"\bworkshop\b",
]))
DATE_RE = re.compile(DATE)
#: how a comment line starts, in the languages of these repos
COMMENT = ("#", "//", "/*", "*", "--", "<!--", ";")
#: a broader POSIX pattern for git grep (no \d, no \b there); HISTORY then decides line by line
GREP = r"20[0-9]{2}-[0-9]{2}-[0-9]{2}|Ruling [0-9]|T[0-9]+(, T[0-9]+)*:|adapt plan|workshop"

#: a test named after an internal plan item instead of what it checks: def test_tg6_..., test_i16_1_...,
#: test_p2r1_1_...; objective ids (test_o9_...) and versions (test_v2_...) are real names
PLAN_TEST = re.compile(r"\bdef test_(?!(?:o|v)\d+_)[a-z]{1,3}\d+(?:[a-z]{1,3}\d+)*(?:_\d+)*_")
#: the same for a vitest name: it("I16.1 ..."), describe("QL2 ..."); objective ids (O9) are real names, and
#: longer codes are not plan items (Prisma's P2002)
PLAN_SPEC = re.compile(r"""\b(?:it|test|describe)(?:\.\w+)*\(\s*["'`](?!O\d+\b)[A-Z]{1,3}\d{1,2}(?:\.\d+)*\b""")
#: a broader POSIX pattern for git grep; PLAN_TEST and PLAN_SPEC then decide line by line
PLAN_GREP = r"def test_[a-z]{1,3}[0-9]|(it|test|describe)(\.[a-z]+)*\( *[\"'`][A-Z]{1,3}[0-9]"

#: git pathspecs of what holds data or history by design
EXCLUDE = [":!:**/CHANGELOG.md", ":!:CHANGELOG.md", ":!:*.lock", ":!:**/package-lock.json",
           ":!:**/pnpm-lock.yaml", ":!:**/yarn.lock", ":!:**/seed/**", ":!:**/seed*.sql", ":!:**/fixtures/**",
           ":!:fixtures/**", ":!:**/golden/**",
           ":!:scripts/tests/test_no_working_notes.py"]


def _data_spans(line: str) -> list[tuple[int, int]]:
    """Where a date on this line is data rather than an explanation."""
    spans = []
    plain = line.replace('"""', "   ").replace("'''", "   ")
    # on a code line a string literal is a value ("2026-09-10 to 2026-09-12"); a comment's quotes are
    # prose, and so is a JSON note ("_about": "...")
    if not line.lstrip().startswith(COMMENT):
        for m in re.finditer(r"""(?<!\w)(["'`])[^\n]*?\1(?!\w)""", plain):
            if not re.search(r'"_\w+"\s*:\s*$', plain[:m.start()]):
                spans.append(m.span())
    spans += [m.span() for m in re.finditer(r"""(?<!['"])['"]20\d{2}-\d{2}-\d{2}""", line)]  # '2026-...
    spans += [m.span() for m in re.finditer(r"=\s*20\d{2}-\d{2}-\d{2}", line)]      # a value: =2026-09-10
    spans += [m.span() for m in re.finditer(DATE + r"[T ]\d{2}:\d{2}", line)]        # a timestamp
    spans += [m.span() for m in re.finditer(r"_at\W{0,4}\s*['\"]?" + DATE, line)]   # created_at: "2026-..."
    return spans


def findings(line: str) -> list[str]:
    """The history this line holds; [] when it holds none."""
    spans = _data_spans(line)
    out = []
    for m in HISTORY.finditer(line):
        if DATE_RE.fullmatch(m.group(0)) and any(a <= m.start() < b for a, b in spans):
            continue
        out.append(m.group(0))
    return out


def scan(repo) -> list[str]:
    """file:line: text, for every line of the repo's tracked text files that holds history."""
    r = subprocess.run(["git", "-C", str(repo), "grep", "-n", "-I", "-E", GREP, "--", "."] + EXCLUDE,
                       capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr
    hits = []
    for row in r.stdout.splitlines():
        path, num, text = row.split(":", 2)
        if findings(text):
            hits.append(f"{path}:{num}: {text.strip()[:160]}")
    return hits


def plan_names(repo) -> list[str]:
    """file:line: text, for every test of the repo's tracked files named after a plan item."""
    r = subprocess.run(["git", "-C", str(repo), "grep", "-n", "-I", "-E", PLAN_GREP, "--", "."] + EXCLUDE,
                       capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr
    hits = []
    for row in r.stdout.splitlines():
        path, num, text = row.split(":", 2)
        if PLAN_TEST.search(text) or PLAN_SPEC.search(text):
            hits.append(f"{path}:{num}: {text.strip()[:160]}")
    return hits


def a_plan_name(line: str) -> bool:
    return bool(PLAN_TEST.search(line) or PLAN_SPEC.search(line))


def test_a_test_named_after_a_plan_item_is_found_and_a_real_name_is_not():
    assert a_plan_name("def test_tg6_a_connection_is_the_endpoint_of_the_target_it_names(client):")
    assert a_plan_name("def test_i16_1_fails_on_a_planted_extra_reader_grant(bed):")
    assert a_plan_name("def test_p2r1_1_block_types_are_fetched_once_within_the_ttl():")
    assert a_plan_name("async def test_wp2_the_old_system_routes_are_gone(client):")
    assert a_plan_name('  it("I16.1 privileges hold", () => {')
    assert a_plan_name("describe('QL2 keys: carried from the card before', () => {")
    assert not a_plan_name("def test_o9_before_o10_and_old_ids_last():")
    assert not a_plan_name("def test_v2_gets_its_own_assessment_and_v1s_is_left_as_it_was(")
    assert not a_plan_name("def test_the_upstream_check_g4_passes_on_the_engine_repos_as_listed(tmp_path):")
    assert not a_plan_name('  it("P2002 on the version: saved by someone else meanwhile", async () => {')
    assert not a_plan_name('  it("c1 keeps fv-mix-1 (the renamed column, same value)", () => {')
    assert not a_plan_name('  it("O9 comes before O10", () => {')


def test_the_root_repo_names_its_tests_for_what_they_check():
    hits = plan_names(ROOT)
    assert hits == [], "tests named after a plan item in the root repo:\n" + "\n".join(hits)


@pytest.mark.parametrize("path", SUBMODULES)
def test_a_submodule_names_its_tests_for_what_they_check(path):
    repo = ROOT / path
    if not (repo / ".git").exists():
        pytest.skip(f"{path} is not checked out")
    hits = plan_names(repo)
    assert hits == [], f"tests named after a plan item in {path}:\n" + "\n".join(hits)


def test_a_dated_explanation_is_history_and_test_data_is_not():
    assert findings("    # The pages' address until 2026-10-04: bookmarks go on to the same page there.")
    assert findings('    """2026-10-06: every requirement is in the README itself."""')
    assert findings("  /* step 4 test tiles (2026-10-03): one per installed test */")
    assert findings("webapp .env.test T7: the mode for plain vitest runs (Ruling 30)")
    assert findings("# importing an endpoint from a file (the workshop's endpoint files)")
    assert not findings('    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", when="2026-09-30 08:00+00")')
    assert not findings("    conn.execute(\"UPDATE t SET occurred_at = '2000-01-01' WHERE a = %s\")")
    assert not findings('    assert "Version 2" in cells and "2026-09-10 to 2026-09-12" in cells')
    assert not findings("    doc = _editor(client, auth, f\"{lay['id']}?period_from=2026-09-10\")")
    assert not findings('  "created_at": "2026-09-01T10:00:00Z",')
    assert not findings('ANTHROPIC_VERSION = "2023-06-01"')
    assert not findings('    assert "No test runs between 2026-01-01 and 2026-01-01 for version 2." in t')
    assert not findings('    return f"{v}T00:00:00+00:00" if v else v')
    assert findings("    // a run's tiles (2026-10-04, see the 'plugin dashboards' note)")
    assert findings('  "_about": "The brand theme (chosen 2026-10-16): the values every app carries, and the fonts",')


def test_the_root_repo_explains_without_history():
    hits = scan(ROOT)
    assert hits == [], "history in the root repo:\n" + "\n".join(hits)


@pytest.mark.parametrize("path", SUBMODULES)
def test_a_submodule_explains_without_history(path):
    repo = ROOT / path
    if not (repo / ".git").exists():
        pytest.skip(f"{path} is not checked out")
    hits = scan(repo)
    assert hits == [], f"history in {path}:\n" + "\n".join(hits)
