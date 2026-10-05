"""Two checks of the verify scripts that depend on how the engine behaves.

1. scripts/verify-rbac.sh: an ordinary account reading the audit log gets 401, not 403 (the engine's
   answer for a verified token that lacks the role, in aisc_backend/auth/keycloak.py).
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


# 1. verify-rbac.sh: the audit log is for admins, so an ordinary account gets 401, not 403


def test_rbac_ordinary_account_reading_audit_log_expects_401():
    text = rbac_text()
    m = re.search(r'^\s*is\s+"the audit log is for admins"\s+(\S+)\s+"\$\(eng \$ENG/audit GET "\$USER"\)"',
                   text, re.M)
    assert m, 'verify-rbac.sh has no `is "the audit log is for admins" ... $USER` assertion'
    assert m.group(1) == "401", (
        f'the audit log check for an ordinary account expects {m.group(1)!r}, want exactly "401" '
        '(Sean\'s answer, adapt plan item 3)')


def test_rbac_audit_log_line_is_exact_not_isnot():
    """The answer is exactly 401, so this stays an `is` (one expected code), never widened to
    `isnot ... 403` (which would accept both)."""
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
    """The admin side of the same check stays `isnot 401 403`."""
    text = rbac_text()
    assert re.search(r'isnot\s+"and an admin may read it"\s+401\s+403\s+"\$\(eng \$ENG/audit GET "\$ADMIN"\)"',
                      text), "the admin audit log check changed; it was not in scope"


# 2. verify-sso.sh section 3: no login of its own, in a dual-mode bundle


def section3_logic() -> str:
    """The decision logic between `bundle=$(curl ...)` and the /admin/ loop. Extracted by anchor, not
    by line number, so it survives edits either side."""
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
    """A dual-mode bundle always carries silent-check-sso/onTokenExpired/aisc-webapp (the engine's
    standalone client is compiled in either way), so a check that fails on finding them fails every build."""
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
    """A bundle carrying the engine's standalone client verbatim, but never started (configurator
    substituted in, Keycloak URL left as the placeholder), must pass."""
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
    """A substituted Keycloak URL in a configurator bundle must fail: the engine could then run its own
    login."""
    bundle = (
        'new Wr({url:"https://sso.example.org/",realm:"aisc",clientId:"aisc-webapp"});'
        'depl("configurator");'
    )
    out = run_section3(bundle)
    assert "NO" in out, f"a substituted (usable) Keycloak URL in a configurator bundle was not caught:\n{out}"


# 2d: the gateway copies the person's token onto every protected request -----------------------

def _copies(text: str) -> bool:
    import importlib.util

    spec = importlib.util.spec_from_file_location("caddy_token_copy", ROOT / "scripts/lib/caddy_token_copy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.protect_copies_token(text)


def test_sso_2d_the_real_gateway_copies_the_token():
    assert _copies((ROOT / "Caddyfile").read_text())


def test_sso_2d_follows_protect_into_the_snippets_it_imports_whatever_the_comments():
    """protect imports strip-and-sign-in, where the forward_auth to oauth2-proxy copies the header: the check
    follows the imports, so comments or new lines in between don't change its answer."""
    text = (ROOT / "Caddyfile").read_text()
    padded = text.replace("(strip-and-sign-in) {", "(strip-and-sign-in) {\n" + "  # a comment\n" * 40, 1)
    assert _copies(padded)


def test_sso_2d_fails_when_no_snippet_copies_it():
    text = (ROOT / "Caddyfile").read_text().replace("copy_headers X-Auth-Request-Access-Token", "", 1)
    assert not _copies(text)


def test_sso_2d_the_check_uses_the_parser():
    assert "caddy_token_copy.py" in SSO.read_text() and "grep -A 12 '(protect)'" not in SSO.read_text()


# the compose files ship no secret: a ${SECRET:-value} fallback is refused --------------------

def _secret_fallback_pattern() -> str:
    m = re.search(r"grep -rqE '([^']+)'", SSO.read_text())
    assert m, "the shipped-secret grep is not in verify-sso.sh"
    return m.group(1)


def _matches(line: str) -> bool:
    return subprocess.run(["grep", "-qE", _secret_fallback_pattern()], input=line, text=True).returncode == 0


import pytest  # noqa: E402


@pytest.mark.parametrize("line", [
    "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}",
    "SUPERSET_SECRET_KEY: ${SUPERSET_SECRET_KEY:-change-me}",
    "DASHBOARD_BRIDGE_TOKEN: ${DASHBOARD_BRIDGE_TOKEN:-abc}",
    "MISTRAL_API_KEY: ${MISTRAL_API_KEY:-sk-1}",
    "AWS_CREDENTIALS: ${AWS_CREDENTIALS:-x}",
    "IMMUDB_PASSWD: ${IMMUDB_PASSWD:-immudb}",
])
def test_a_shipped_secret_fallback_is_caught(line):
    assert _matches(line)


@pytest.mark.parametrize("line", [
    "CONNECTIONS_RUN_KEY_TTL_S: ${CONNECTIONS_RUN_KEY_TTL_S:-600}",
    "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?run scripts/secrets.sh first}",
    "LEDGER_MODE: ${LEDGER_MODE:-off}",
])
def test_a_setting_that_only_names_a_key_is_not_a_secret(line):
    """A lifetime of run keys is a number of seconds, not a key; a required secret (:?) ships nothing."""
    assert not _matches(line)


def test_sso_the_project_page_check_follows_the_page_as_designed():
    """The project page is two blocks: Plan the assessment (Qualify, Set control objectives, Identify tests
    and controls) and the AI Assessment Sandbox below it (docs/superpowers/results-nav-2026-10-03,
    02-sandbox-specs.md S1). The check looks for those cards, in that order, not for six steps."""
    text = SSO.read_text()
    assert "qualification-card" in text and "control-objectives-card" in text
    assert "catalogue-card" in text and "sandbox-card" in text and 'plan-block' in text
    assert '[ "$n" = "6" ]' not in text


def test_rbac_the_dashboard_role_check_reads_every_role_of_the_account():
    """An ordinary account is AiscViewer plus one AiscProject_<hex> role per project it is in (granted at
    sign-in). The check reads all its roles, not one row of an unordered query: it passes on AiscViewer
    with project roles, and fails on any other role (Gamma, Alpha, Admin) or without AiscViewer."""
    text = RBAC.read_text()
    block = text[text.index("landed=$("):text.index("writes=$(")]
    assert "tail -1" not in block and "AiscProject_" in block and "AiscViewer" in block
