"""A number named in the ledger's settings is a rule the code applies, and a count in the verify report is one
the verifier makes: a name nothing reads would describe a rule that isn't there."""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from platform_service.ledger import settings, verify

PACKAGE = Path(settings.__file__).resolve().parents[1]


def _sources():
    return [p.read_text() for p in PACKAGE.rglob("*.py") if p.resolve() != Path(settings.__file__).resolve()]


def test_every_setting_is_read_by_the_platform():
    names = [n for n in vars(settings) if n.isupper()]
    sources = _sources()
    unread = [n for n in names if not any(f"settings.{n}" in s or f"import {n}" in s or f" {n}," in s for s in sources)]
    assert unread == []


def test_every_count_of_the_report_is_set_by_the_verifier():
    tree = ast.parse(Path(verify.__file__).read_text())
    assigned = {node.attr for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)}
    assigned |= {node.target.attr for node in ast.walk(tree)
                 if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute)}
    never = [f.name for f in dataclasses.fields(verify.Report) if f.name not in assigned]
    assert never == []
