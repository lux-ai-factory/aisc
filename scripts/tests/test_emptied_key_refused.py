"""An emptied line for a key that opens stored data is refused, never regenerated.

PLATFORM_SECRETS_KEY opens every stored LLM key, DJANGO_SECRET_KEY the engine's stored credentials, and
PLATFORM_LEDGER_KEYS verifies the ledger's past signatures. A line left as `NAME=` in env.secrets of an
existing install used to get a fresh value, and every value encrypted or signed under the old one became
unreadable or unverifiable. Now secrets (and start, which runs it) stop with a message naming the key and
change no file. Other empty values are still made again.

secrets.sh runs on a scratch copy; nothing in the repo is written, nothing is started, and no value is
printed.
"""
import re

import pytest

from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets
from test_secrets_hardening import _digest, _run

KEYS = ["PLATFORM_SECRETS_KEY", "DJANGO_SECRET_KEY", "PLATFORM_LEDGER_KEYS"]


@pytest.mark.parametrize("name", KEYS)
def test_an_emptied_key_line_is_refused_and_nothing_changes(scratch, name):  # noqa: F811
    run_secrets(scratch)
    text = (scratch / "env.secrets").read_text()
    (scratch / "env.secrets").write_text(re.sub(rf"^{name}=.*$", f"{name}=", text, flags=re.M))
    secrets_before = _digest((scratch / "env.secrets").read_text())
    runtime_before = _digest((scratch / "env.runtime").read_text())
    r = _run(scratch)
    assert r.returncode != 0, f"an emptied {name} was generated again instead of refused"
    assert name in r.stdout + r.stderr, "the refusal does not name the key"
    assert _digest((scratch / "env.secrets").read_text()) == secrets_before, "env.secrets was changed"
    assert _digest((scratch / "env.runtime").read_text()) == runtime_before, "env.runtime was changed"


def test_an_emptied_ordinary_secret_is_still_made_again(scratch):  # noqa: F811
    run_secrets(scratch)
    text = (scratch / "env.secrets").read_text()
    (scratch / "env.secrets").write_text(re.sub(r"^INTERNAL_API_KEY=.*$", "INTERNAL_API_KEY=", text, flags=re.M))
    r = _run(scratch)
    assert r.returncode == 0, r.stderr[-2000:]
    assert re.search(r"^INTERNAL_API_KEY=[0-9a-f]{64}$", (scratch / "env.secrets").read_text(), re.M)
