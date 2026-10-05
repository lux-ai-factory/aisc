"""immudb on the development stack: its superuser password is not in any tracked file, and it signs
its states with a generated key. Reads the files only."""
import yaml

from conftest import ROOT

TRACKED = ["env.development", "env.plugin_downloader"]


def test_no_tracked_file_holds_the_immudb_superuser_password():
    for name in TRACKED:
        lines = [l for l in (ROOT / name).read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
        assert not [l for l in lines if l.startswith("IMMUDB_ADMIN_PASSWORD=")], f"{name} still sets it"


def _immudb():
    return yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]["immudb"]


def test_immudb_signs_its_states_with_the_generated_key():
    svc = _immudb()
    env = svc["environment"]
    assert env.get("IMMUDB_SIGNINGKEY") == "/keys/signing.key"
    assert any(str(v).startswith("./immudb-signing.key:/keys/signing.key:ro") for v in svc["volumes"])


def test_immudb_still_takes_its_superuser_password_from_the_environment():
    env = _immudb()["environment"]
    assert env["IMMUDB_ADMIN_PASSWORD"] == "${IMMUDB_ADMIN_PASSWORD:?run scripts/secrets.sh first}"
    assert env["IMMUDB_FORCE_ADMIN_PASSWORD"] == "true"


def test_the_signing_key_is_never_committed():
    gitignore = (ROOT / ".gitignore").read_text().splitlines()
    assert "immudb-signing.key" in gitignore and "immudb-signing.pub" in gitignore
