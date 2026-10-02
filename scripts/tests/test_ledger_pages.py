"""A6: the Activity log page and the beacon script (spec 6.3, 3.5). The page stays thin: the platform
filters, verifies and names people; the page lays rows out with textContent only."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "homepage/logs.html"
PROJECT = ROOT / "homepage/project.html"
BEACON = ROOT / "homepage/assets/ledger-beacon.js"


def scripts(html: str) -> list[str]:
    return [s for s in re.findall(r"<script>(.*?)</script>", html, re.S) if s.strip()]


def test_the_page_reads_the_verified_events_route_and_never_writes_html():
    html = LOGS.read_text()
    assert "/ledger/events" in html and "innerHTML" not in html
    assert "ALARM" in html                                           # a 409 is shown as an alarm, not hidden


def test_the_export_link_is_offered_to_owners_and_admins_only():
    html = LOGS.read_text()
    assert re.search(r"a\.admin \|\| a\.role === 'owner'\)[^}]*ledger/export", html, re.S)


def test_hidden_wins_over_the_buttons_display():
    """Found in a headless render: `button{display:inline-flex}` showed hidden buttons, and would have
    shown the export link to every member."""
    assert "[hidden]{display:none !important}" in LOGS.read_text()


def test_the_manage_menu_has_the_activity_log_for_members():
    html = PROJECT.read_text()
    assert '<a id="activity-log" class="member-only" hidden>Activity log</a>' in html
    assert "'/logs.html?project=' + encodeURIComponent(slug)" in html


def test_the_beacon_is_text_plain_to_the_platform_and_never_throws():
    js = BEACON.read_text()
    assert "sendBeacon('/api/ledger/beacon'" in js and "text/plain" in js and "catch" in js
    for page in (LOGS, PROJECT):
        assert '<script src="/assets/ledger-beacon.js"></script>' in page.read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("page", [LOGS, PROJECT])
def test_the_scripts_parse(tmp_path, page):
    for n, body in enumerate(scripts(page.read_text()) + [BEACON.read_text()]):
        f = tmp_path / f"s{n}.js"
        f.write_text(body)
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
