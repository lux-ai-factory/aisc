"""The safe error text shown to editors is one function kept as two copies, one per app: they stay byte-identical."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_COPY = ROOT / "apps/qualification/services/agents/fill/errors.py"
CONTROL_OBJECTIVES_COPY = ROOT / "apps/control-objectives/src/aisc_control_objectives/errors.py"


def test_both_copies_exist_and_are_byte_identical():
    assert QUALIFICATION_COPY.read_bytes() == CONTROL_OBJECTIVES_COPY.read_bytes()
