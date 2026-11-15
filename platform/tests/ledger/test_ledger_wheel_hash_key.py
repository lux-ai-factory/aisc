"""The ledger's registry lets plugin.installed carry the installed wheel's sha256, and for a local plugin its
code digest, so an install event that names them is not refused."""
from platform_service.ledger.registry import REGISTRY


def test_plugin_installed_declares_the_wheel_hash_key():
    keys = REGISTRY["plugin.installed"].details_keys
    assert "wheel_sha256" in keys, keys
    assert "code_digest" in keys, keys
