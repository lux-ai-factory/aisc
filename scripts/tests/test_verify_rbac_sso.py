"""Task 6c: two verify checks follow the adapted engine (2026-09-28-engine-adapt-to-master).

1. scripts/verify-rbac.sh: an ordinary account reading the audit log now gets 401, not 403 (Sean's
   answer for a verified token that lacks the role; adapt plan item 3; aisc_backend/auth/keycloak.py
   is byte-identical to Sean's master).
2. scripts/verify-sso.sh section 3: the engine's bundle is one bundle for both modes, so grepping it
   for silent-check-sso/onTokenExpired/aisc-webapp always finds them and proves nothing. What proves
   "the engine has no login of its own" in a dual-mode bundle: the mode placeholder was substituted to
   "configurator", and the Keycloak client's url: is still the unsubstituted placeholder APP_KEYCLOAK_URL.

Static checks read the script text. The section-3 logic is also run against fake bundle strings (never
the live stack): the case block between the `bundle=$(curl ...)` line and the `for path in /admin/` line
is extracted and executed in a throwaway bash process with fake ok()/no() functions and a fixed $bundle.

    uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' python -m pytest -q \
        -p no:cacheprovider scripts/tests/test_verify_rbac_sso.py
"""

from __future__ import annotations

import re
import subprocess

from conftest import ROOT

RBAC = ROOT / "scripts/verify-rbac.sh"
SSO = ROOT / "scripts/verify-sso.sh"


def rbac_text() -> str:
    assert RBAC.exists(), "scripts/verify-rbac.sh missing"
    return RBAC.read_text()


def sso_text() -> str:
    assert SSO.exists(), "scripts/verify-sso.sh missing"
    return SSO.read_text()


# ── 1. verify-rbac.sh: the audit log is for admins -> 401, not 403 ─────────────


def test_rbac_ordinary_account_reading_audit_log_expects_401():
    text = rbac_text()
    m = re.search(r'^\s*is\s+"the audit log is for admins"\s+(\S+)\s+"\$\(eng \$ENG/audit GET "\$USER"\)"',
                   text, re.M)
    assert m, 'verify-rbac.sh has no `is "the audit log is for admins" ... $USER` assertion'
    assert m.group(1) == "401", (
        f'the audit log check for an ordinary account expects {m.group(1)!r}, want exactly "401" '
        '(Sean\'s answer, adapt plan item 3)')


def test_rbac_audit_log_line_is_exact_not_isnot():
    """The brief: "Do not accept 401 or 403": the answer is now exactly 401, so this stays an `is`
    (single expected code), never widened to `isnot ... 403` (which would accept both)."""
    text = rbac_text()
    assert not re.search(r'isnot\s+"the audit log is for admins"', text), (
        "the ordinary-account audit log check was widened to isnot (accepts more than one code)")


def test_rbac_audit_log_change_is_explained_in_a_comment():
    text = rbac_text()
    idx = text.index('is "the audit log is for admins"')
    before = text[max(0, idx - 400):idx]
    assert "401" in before or "401" in text[idx:idx + 200], "no comment near the audit log check"
    assert "Sean" in before, "the comment does not say this is Sean's answer"
    assert re.search(r"item 3|adapt", before, re.I), "the comment does not point at the adapt plan"


def test_rbac_admin_audit_log_check_is_unchanged():
    """The admin side of the same check (isnot 401 403) is untouched by this task."""
    text = rbac_text()
    assert re.search(r'isnot\s+"and an admin may read it"\s+401\s+403\s+"\$\(eng \$ENG/audit GET "\$ADMIN"\)"',
                      text), "the admin audit log check changed; it was not in scope"


# ── 2. verify-sso.sh section 3: no login of its own, in a dual-mode bundle ────


def section3_logic() -> str:
    """The decision logic between `bundle=$(curl ...)` and the /admin/ loop: whatever replaced the
    old bare grep. Extracted by anchor, not by line number, so it survives edits either side."""
    text = sso_text()
    start_marker = 'bundle=$(curl -s -b "$J" --max-time 20 "http://localhost$js")'
    end_marker = 'for path in /admin/ /_allauth/browser/v1/config; do'
    assert start_marker in text, "verify-sso.sh section 3: bundle= line not found (script restructured?)"
    assert end_marker in text, "verify-sso.sh section 3: the /admin/ loop not found (script restructured?)"
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker)
    assert start < end, "verify-sso.sh section 3: markers out of order"
    return text[start:end]


def test_sso_section3_no_longer_a_bare_grep_for_always_present_markers():
    """A dual-mode bundle always carries silent-check-sso/onTokenExpired/aisc-webapp (Sean's standalone
    client is compiled in either way), so a check that fails on finding them fails every build."""
    logic = section3_logic()
    assert "silent-check-sso" not in logic, "still greps for silent-check-sso, always present in a dual-mode bundle"
    assert "onTokenExpired" not in logic, "still greps for onTokenExpired, always present in a dual-mode bundle"


def test_sso_section3_checks_the_deployment_placeholder_and_keycloak_url():
    logic = section3_logic()
    assert "APP_DEPLOYMENT" in logic, "no check for the mode placeholder (apps/webapp/.env: VITE_DEPLOYMENT=APP_DEPLOYMENT)"
    assert "APP_KEYCLOAK_URL" in logic, "no check for the Keycloak client's unsubstituted URL placeholder"


def run_section3(bundle: str) -> str:
    logic = section3_logic()
    harness = f'''#!/usr/bin/env bash
set -uo pipefail
ok(){{ printf 'OK %s\\n' "$1"; }}
no(){{ printf 'NO %s\\n' "$1"; }}
bundle={bundle!r}
{logic}
'''
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.stderr == "" or "unbound variable" not in r.stderr, r.stderr
    return r.stdout


def test_sso_section3_passes_on_a_correctly_substituted_configurator_bundle():
    """The bug this task fixes: a bundle carrying Sean's standalone client verbatim, but never started
    (configurator substituted in, Keycloak URL left as the placeholder), must PASS."""
    bundle = (
        'function q(){}var silentCheckSso="silent-check-sso.html";'
        'keycloak.onTokenExpired=function(){};'
        'new Wr({url:"APP_KEYCLOAK_URL",realm:"aisc",clientId:"aisc-webapp"});'
        'function depl(e){if(e===void 0)return"standalone";'
        'if(e==="standalone"||e==="configurator")return e;throw new Error("bad: "+e)}'
        'depl("configurator");'
    )
    out = run_section3(bundle)
    assert "NO" not in out, f"a correctly-substituted configurator bundle failed:\n{out}"
    assert "OK" in out


def test_sso_section3_fails_when_the_deployment_placeholder_was_never_substituted():
    bundle = (
        'new Wr({url:"APP_KEYCLOAK_URL",realm:"aisc",clientId:"aisc-webapp"});'
        'depl("APP_DEPLOYMENT");'
    )
    out = run_section3(bundle)
    assert "NO" in out, f"an unsubstituted APP_DEPLOYMENT placeholder was not caught:\n{out}"


def test_sso_section3_fails_when_the_keycloak_url_was_substituted_to_a_real_address():
    """A substituted Keycloak URL in a configurator bundle is the FAIL case the brief calls out
    explicitly: the engine would then be able to run its own login."""
    bundle = (
        'new Wr({url:"https://sso.example.org/",realm:"aisc",clientId:"aisc-webapp"});'
        'depl("configurator");'
    )
    out = run_section3(bundle)
    assert "NO" in out, f"a substituted (usable) Keycloak URL in a configurator bundle was not caught:\n{out}"
