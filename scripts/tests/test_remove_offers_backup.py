"""`aisc.py remove` deletes the install's volumes (the ledger, its key, MinIO's files, every database). Before
it does, it offers the backup, and says where it would go; nothing is deleted before that offer.

scripts/aisc.py is loaded from a scratch copy; Docker is never called: the compose run and the questions are
replaced by recorders.
"""
from conftest import aisc_py, copy_install_scripts


def test_remove_offers_a_backup_before_deleting_the_volumes(tmp_path, monkeypatch):
    # a folder name of its own: the prompt names the folder, and the test's own name holds the word looked for
    tmp_path = tmp_path / "install"
    tmp_path.mkdir()
    copy_install_scripts(tmp_path)
    (tmp_path / "env.secrets").write_text("AISC_INSTALL=abc123\n")
    aisc = aisc_py(tmp_path)
    events = []

    def asked(prompt=""):
        events.append(("asked", prompt))
        return tmp_path.name

    monkeypatch.setattr("builtins.input", asked)
    monkeypatch.setattr(aisc.stack, "own_compose", lambda verb: ["docker", "compose", "-p", "aisc-t-remove"])
    monkeypatch.setattr(aisc.stack, "run_compose", lambda argv: events.append(("compose", " ".join(argv))))
    monkeypatch.setattr(aisc.stack, "ROOT", tmp_path)
    try:
        aisc.remove([])
    except Exception:  # noqa: BLE001 - a refusal is fine here: what was offered first is what counts
        pass
    down = next((i for i, e in enumerate(events) if e[0] == "compose" and "down" in e[1]), len(events))
    offered = [e for e in events[:down] if "backup" in str(e[1]).lower()]
    assert offered, f"no backup was offered before the volumes were deleted: {[e[0] for e in events]}"
