"""Ledger events are delivered by one loop in Python, aisc_identity.ledger_delivery, which the engine and the
results dashboard call; the agents, which cannot import it, carry a byte-identical copy. TypeScript keeps its one
module, shared/ledger-ts.

Read-only: the source files as text.
"""

from conftest import ROOT

SHARED = ROOT / "shared/identity/aisc_identity/ledger_delivery.py"
AGENTS_COPY = ROOT / "apps/qualification/services/agents/fill/vendor/ledger_delivery.py"


def test_the_python_senders_use_the_one_delivery_loop():
    own = [f for f in ("apps/backend/aisc_backend/ledger.py", "apps/results-dashboard/aisc_ext/ledger.py")
           if "ledger_delivery" not in (ROOT / f).read_text() or "def _deliver(" in (ROOT / f).read_text()]
    assert own == [], "these keep a delivery loop of their own"


def test_the_agents_copy_is_byte_identical():
    assert SHARED.is_file(), "no aisc_identity/ledger_delivery.py"
    assert AGENTS_COPY.is_file(), "the agents carry no copy of the delivery loop"
    assert AGENTS_COPY.read_bytes() == SHARED.read_bytes()
    assert "vendor.ledger_delivery" in (ROOT / "apps/qualification/services/agents/fill/ledger.py").read_text()
