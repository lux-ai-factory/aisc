"""Every new project takes a ledger database from the pool, and only the start-up job (ledger-pool, the one
holder of immudb's superuser password besides immudb) refills it. So the pool is kept large enough that a
stack runs out only after many projects between two starts; when it does, new projects wait for their log
and deleting one waits too, until the next start or scripts/ledger-pool.sh."""
import re

from conftest import ROOT

POOL = 50


def test_the_start_up_job_keeps_fifty_free_databases():
    compose = (ROOT / "docker-compose.development.yml").read_text()
    assert re.search(r'"top-up", "--wait", "300", "\$\{LEDGER_POOL:-' + str(POOL) + r'\}"', compose)


def test_the_platforms_own_default_is_the_same():
    settings = (ROOT / "platform/platform_service/ledger/settings.py").read_text()
    assert re.search(rf"^LEDGER_POOL = {POOL}\b", settings, re.M)
