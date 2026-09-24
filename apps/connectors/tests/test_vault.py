import uuid

import pytest


@pytest.fixture
def connector(db):
    pid = uuid.uuid4()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO connector.connector (pid, project_pid, ai_system_pid, name, slug, kind,"
            " environment, created_by) VALUES (%s, %s, %s, 'X', 'x', 'manual', 'sandbox', 't')",
            (pid, uuid.uuid4(), uuid.uuid4()),
        )
    return pid


def test_put_then_plain_round_trips(connector):
    from aisc_connectors import vault

    vault.put(connector, "api_key", "sk-live-1234567890")
    assert vault.plain(connector, "api_key") == "sk-live-1234567890"


def test_describe_never_returns_the_value(connector):
    from aisc_connectors import vault

    vault.put(connector, "api_key", "sk-live-1234567890")
    described = vault.describe(connector)
    assert [d["name"] for d in described] == ["api_key"]
    assert "sk-live-1234567890" not in repr(described)
    assert described[0]["masked"] == "sk****90"


def test_short_values_are_fully_masked(connector):
    from aisc_connectors import vault

    assert vault.put(connector, "password", "abc")["masked"] == "****"


def test_the_ciphertext_is_not_the_value(db, connector):
    from aisc_connectors import vault

    vault.put(connector, "token", "plain-token-value")
    with db.connection() as conn:
        row = conn.execute("SELECT ciphertext FROM connector.secret").fetchone()
    assert "plain-token-value" not in row["ciphertext"]


def test_unknown_names_are_refused(connector):
    from aisc_connectors import vault

    with pytest.raises(vault.UnknownSecretName):
        vault.put(connector, "anything", "x")


def test_no_key_is_a_misconfiguration(connector, monkeypatch):
    from aisc_connectors import vault

    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", "")
    with pytest.raises(vault.VaultMisconfigured):
        vault.put(connector, "token", "x")


def test_rotation_reencrypts_under_the_newest_key(connector, monkeypatch, secrets_key):
    from cryptography.fernet import Fernet

    from aisc_connectors import vault

    vault.put(connector, "token", "keep-me")
    newest = Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", f"{newest},{secrets_key}")
    assert vault.rotate() == 1
    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", newest)
    assert vault.plain(connector, "token") == "keep-me"


def test_a_secret_under_a_removed_key_is_unreadable(connector, monkeypatch, secrets_key):
    from cryptography.fernet import Fernet

    from aisc_connectors import vault

    vault.put(connector, "token", "keep-me")
    other = Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", other)
    with pytest.raises(vault.SecretUnreadable):
        vault.plain(connector, "token")


def test_delete_removes_the_secret(connector):
    from aisc_connectors import vault

    vault.put(connector, "token", "x")
    assert vault.delete(connector, "token") is True
    assert vault.plain(connector, "token") is None
    assert vault.describe(connector) == []
    assert vault.delete(connector, "token") is False


def test_malformed_key_is_a_misconfiguration(connector, monkeypatch):
    from aisc_connectors import vault

    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", "not-a-fernet-key")
    with pytest.raises(vault.VaultMisconfigured):
        vault.put(connector, "token", "x")
