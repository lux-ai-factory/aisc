"""C5: a Next.js server action POSTs to the page it is mounted on, so the page its form really lives on
must be one its registry action's `caused_by` names (phase 5 review B1: the card form had moved from
/qualify/new to /system/edit, and every card's creation would have been rejected). The pages are found
in the code, by following imports from the actions module up to each page.tsx that renders it."""
import re
import sys
from pathlib import Path

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "platform"))
APP = ROOT / "apps" / "qualification"
SRC = APP / "src"
IMPORT = re.compile(r"""from\s+["']([^"']+)["']""")
#: Action modules no page renders today, and why. Each must really have no page: once one is mounted
#: again, it is checked like the rest.
UNMOUNTED = {
    "apps/qualification/src/app/p/[project]/qualify/[id]/component-actions.ts":
        "the components panel is off the card page (test/unit/cardPageLayout.test.ts pins it)",
}


def _resolve(importer: Path, spec: str) -> Path | None:
    if spec.startswith("@/"):
        base = SRC / spec[2:]
    elif spec.startswith("."):
        base = (importer.parent / spec).resolve()
    else:
        return None
    for candidate in (base.with_suffix(".ts"), base.with_suffix(".tsx"), base / "index.ts", base / "index.tsx"):
        if candidate.exists():
            return candidate.resolve()
    return None


def _importers() -> dict[Path, set[Path]]:
    out: dict[Path, set[Path]] = {}
    for f in SRC.rglob("*.ts*"):
        for spec in IMPORT.findall(f.read_text(errors="replace")):
            target = _resolve(f, spec)
            if target is not None:
                out.setdefault(target, set()).add(f.resolve())
    return out


def pages_of(module: Path, importers, depth: int = 4) -> set[Path]:
    """Every page.tsx that renders `module`, following imports up `depth` hops."""
    found, frontier, seen = set(), {module.resolve()}, set()
    for _ in range(depth):
        nxt = set()
        for m in frontier:
            for importer in importers.get(m, ()):
                if importer in seen:
                    continue
                seen.add(importer)
                (found if importer.name == "page.tsx" else nxt).add(importer)
        frontier = nxt
    return found


def url_of(page: Path) -> str:
    parts = [p for p in page.parent.relative_to(SRC / "app").parts if not p.startswith("(")]
    sample = ["slug" if p == "[project]" else ("x1" if p.startswith("[") else p) for p in parts]
    return "/qualification/" + "/".join(sample)


def server_actions():
    from platform_service.ledger.registry import REGISTRY

    out = []
    for action in REGISTRY.values():
        causes = [re.compile(c[2]) for c in action.caused_by if c[0] == "qualification" and c[1] == "ACTION"]
        for app, file, function in action.routes:
            if app == "qualification" and causes:
                out.append((action.name, ROOT / file, function, causes))
    return out


@pytest.mark.parametrize("name, module, function, causes", server_actions(),
                         ids=[f"{a[0]}:{a[2]}" for a in server_actions()])
def test_every_page_a_server_action_is_mounted_on_is_a_cause_of_its_action(name, module, function, causes):
    pages = pages_of(module, _importers())
    if str(module.relative_to(ROOT)) in UNMOUNTED:
        assert not pages, f"{module.relative_to(ROOT)} is mounted again: take it off UNMOUNTED"
        return
    assert pages, f"{module.relative_to(ROOT)} is rendered by no page"
    wrong = sorted(url_of(p) for p in pages if not any(c.match(url_of(p)) for c in causes))
    assert not wrong, f"{name} ({function}) is posted from {wrong}, which its caused_by does not name"
