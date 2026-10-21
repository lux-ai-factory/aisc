"""Every tracked file, the submodules' included, can be checked out on Windows: no name Windows reserves
(con, prn, aux, nul, com1-9, lpt1-9, with any extension), no character it refuses in a name, no two paths
that differ only in letter case, and no path longer than its 260-character limit leaves room for."""
import re
import subprocess

from conftest import ROOT

RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", re.I)
REFUSED = re.compile(r'[<>:"\\|?*]')
# what is left of Windows' 260 characters under a clone in a user's own folder
LONGEST = 180


def tracked():
    out = subprocess.run(["git", "ls-files", "--recurse-submodules"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    return out.splitlines()


def test_no_name_windows_reserves():
    bad = [p for p in tracked() if any(RESERVED.match(part) for part in p.split("/"))]
    assert bad == [], bad


def test_no_character_windows_refuses_in_a_name():
    bad = [p for p in tracked() if REFUSED.search(p) or any(part.endswith((" ", ".")) for part in p.split("/"))]
    assert bad == [], bad


def test_no_two_paths_differ_only_in_letter_case():
    seen, bad = {}, []
    for p in tracked():
        if p.lower() in seen:
            bad.append((seen[p.lower()], p))
        seen[p.lower()] = p
    assert bad == [], bad


def test_no_path_too_long_for_a_clone_in_a_user_folder():
    bad = [p for p in tracked() if len(p) > LONGEST]
    assert bad == [], bad
