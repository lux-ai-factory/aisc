"""scripts/clean-old-secrets.sh: counts first, then an encrypted backup outside the repository, the clean, a
verification, and the backup deleted only once the verification passed. It never prints a value, a password or
the passphrase.

A throwaway postgres:15-alpine (scripts/lib/throwaway-pg.sh, never the host's 5432) holds the `platform` database
(core.outbox, ledger.content from the platform migrations) and one project database with minimal engine tables, a
configuration holding PLANTED. The engine command, the platform command and the checker are stand-ins in tmp_path
that record their arguments and print canned lines: counts above zero until an apply ran, zeros after.

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_clean_old_secrets_script.py
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import textwrap
import uuid

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts/clean-old-secrets.sh"
TPG = ROOT / "scripts/lib/throwaway-pg.sh"
PLANTED = "planted-secret-0123456789"
PASSPHRASE = "p" * 20
PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6c"
PROJECT_DB = "project_" + PID.replace("-", "")
PROJECT_TABLES = 3
PLATFORM_TABLES = 2


def _docker():
    return shutil.which("docker") and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _docker(), reason="needs docker for a throwaway postgres")


@pytest.fixture(scope="module")
def postgres():
    """The throwaway server, kept for the module and removed after it."""
    script = textwrap.dedent(f"""\
        set -e
        export TPG_OWN_TRAP=1
        . "{TPG}"
        tpg_start secrets-script >/dev/null
        tpg_init_platform "{ROOT}"
        for f in $(ls "{ROOT}/platform/migrations" | sort); do
          tpg_platform_migration platform "{ROOT}/platform/migrations/$f" >/dev/null
        done
        tpg_su postgres -c 'CREATE DATABASE "{PROJECT_DB}"' >/dev/null
        tpg_su {PROJECT_DB} -c "CREATE SCHEMA engine;
          CREATE TABLE engine.aisc_backend_ledgeroutbox (id int, event jsonb);
          CREATE TABLE engine.aisc_backend_pluginconfig (id int, config jsonb);
          CREATE TABLE engine.aisc_backend_evaluationplugin (id int, error_message text);
          INSERT INTO engine.aisc_backend_pluginconfig VALUES (1, '{{\\"api_key\\": \\"{PLANTED}\\"}}');" >/dev/null
        tpg_su platform -c "INSERT INTO ledger.content (log, event_id, content)
          VALUES ('ledgertest', 'e1', '{{\\"config\\": {{\\"judge_api_key\\": \\"{PLANTED}\\"}}}}')" >/dev/null
        echo "$TPG_NAME"
        """)
    r = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=600)
    name = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    try:
        assert r.returncode == 0, r.stderr[-1500:]
        yield name
    finally:
        if name.startswith("aisc-t-"):
            subprocess.run(["docker", "rm", "-fv", name], capture_output=True)


ENGINE = """\
import json, os, sys
d = os.environ["STANDIN_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(["engine", args]) + "\\n")
db = "{db}"
applying = bool(args) and args[0] == "apply"
scrub_text = "--scrub-config-text" in args
# a kept text field that may hold a key: named for review, or (on request) scrubbed and named to rotate
text_line = (f"{{db}}: rotate plugin=aisc-plugin-b field=prompt configs=1" if scrub_text
             else f"{{db}}: review plugin=aisc-plugin-b field=prompt configs=1")
if applying and os.environ.get("STANDIN_ENGINE_APPLY_EXIT"):
    sys.exit(int(os.environ["STANDIN_ENGINE_APPLY_EXIT"]))
cleaned = os.path.exists(os.path.join(d, "engine-applied")) or os.environ.get("STANDIN_ZEROS")
if applying:
    open(os.path.join(d, "engine-applied"), "w").close()
    print(f"{{db}}: aisc_backend_ledgeroutbox rows_masked=1")
    print(f"{{db}}: aisc_backend_pluginconfig rows_changed=1 fields_dropped=1")
    print(f"{{db}}: aisc_backend_evaluationplugin rows_scrubbed=0")
    print(f"{{db}}: rotate plugin=aisc-plugin-a field=api_key configs=1")
    print(text_line)
    print("total: rows_masked=1 rows_changed=1 fields_dropped=1 rows_scrubbed=0")
elif cleaned:
    print(f"{{db}}: aisc_backend_ledgeroutbox rows_to_mask=0")
    print(f"{{db}}: aisc_backend_pluginconfig rows_to_change=0 fields_to_drop=0")
    print(f"{{db}}: aisc_backend_evaluationplugin rows_to_scrub=0")
    print("total: rows_to_mask=0 rows_to_change=0 fields_to_drop=0 rows_to_scrub=0")
else:
    print(f"{{db}}: aisc_backend_ledgeroutbox rows_to_mask=1")
    print(f"{{db}}: aisc_backend_pluginconfig rows_to_change=1 fields_to_drop=1")
    print(f"{{db}}: aisc_backend_evaluationplugin rows_to_scrub=0")
    print(f"{{db}}: rotate plugin=aisc-plugin-a field=api_key configs=1")
    print(text_line)
    print("total: rows_to_mask=1 rows_to_change=1 fields_to_drop=1 rows_to_scrub=0")
"""

PLATFORM = """\
import json, os, sys
d = os.environ["STANDIN_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(["platform", args]) + "\\n")
pid = "{pid}"
command = args[0] if args else ""
cleaned = os.path.exists(os.path.join(d, "platform-applied")) or os.environ.get("STANDIN_ZEROS")
if command == "export":
    print(json.dumps({{"entry": {{"seq": 1, "project_pid": args[1]}}, "proof": {{}}}}))
    print(json.dumps({{"head": {{"seq": 1}}}}))
elif command == "apply":
    open(os.path.join(d, "platform-applied"), "w").close()
    print(f"project {{pid}}: core.outbox rows_masked=1")
    print(f"project {{pid}}: ledger.content rows_redacted=1 events_appended=1")
    print(f"project {{pid}}: ledger.outbox rows_with_secret_shape=0 (scan only)")
    print(f"project {{pid}}: rotate item=plugin-pid field=judge_api_key events=1")
    print("total: rows_masked=1 rows_redacted=1 events_appended=1 rows_with_secret_shape=0")
elif command == "count" and cleaned:
    print(f"project {{pid}}: core.outbox rows_to_mask=0")
    print(f"project {{pid}}: ledger.content rows_to_redact=0 events_to_append=0")
    print(f"project {{pid}}: ledger.outbox rows_with_secret_shape=0 (scan only)")
    print("total: rows_to_mask=0 rows_to_redact=0 events_to_append=0 rows_with_secret_shape=0")
elif command == "count":
    print(f"project {{pid}}: core.outbox rows_to_mask=1")
    print(f"project {{pid}}: ledger.content rows_to_redact=1 events_to_append=1")
    print(f"project {{pid}}: ledger.outbox rows_with_secret_shape=0 (scan only)")
    print(f"project {{pid}}: rotate item=plugin-pid field=judge_api_key events=1")
    print("total: rows_to_mask=1 rows_to_redact=1 events_to_append=1 rows_with_secret_shape=0")
else:
    sys.exit(2)
"""

CHECKER = """\
import json, os, sys
d = os.environ["STANDIN_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(["checker", args, os.path.exists(args[-1])]) + "\\n")
print("ok: log ledgertest, project {pid}, 1 entries, format chain, signed; frozen contents checked")
sys.exit(int(os.environ.get("STANDIN_CHECKER_EXIT") or 0))
"""


@pytest.fixture
def bed(tmp_path, postgres):
    """The stand-ins, a backup folder outside the repository, and a way to run the script."""
    standins = tmp_path / "standins"
    standins.mkdir()
    for name, body in (("engine", ENGINE.format(db=PROJECT_DB)), ("platform", PLATFORM.format(pid=PID)),
                       ("checker", CHECKER.format(pid=PID))):
        path = standins / f"{name}.py"
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)
    key = tmp_path / "signing.pub"
    key.write_text("-----BEGIN PUBLIC KEY-----\nstand-in\n-----END PUBLIC KEY-----\n")
    backups = tmp_path / "backups"
    backups.mkdir()
    outputs = []

    def run(*args, **env_over):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLEAN_SECRETS_", "AISC_CLEANUP_"))}
        env.update({"STANDIN_DIR": str(standins), "AISC_CLEANUP_BACKUP_PASSPHRASE": PASSPHRASE,
                    "CLEAN_SECRETS_PG_CONTAINER": postgres,
                    "CLEAN_SECRETS_ENGINE_CMD": str(standins / "engine.py"),
                    "CLEAN_SECRETS_PLATFORM_CMD": str(standins / "platform.py"),
                    "CLEAN_SECRETS_CHECKER": str(standins / "checker.py"),
                    "CLEAN_SECRETS_PUBLIC_KEY": str(key), "CLEAN_SECRETS_EXTRA_FREE_BYTES": "0"})
        for k, v in env_over.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        r = subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=600)
        outputs.append(r.stdout + r.stderr)
        assert PLANTED not in r.stdout + r.stderr
        assert PASSPHRASE not in r.stdout + r.stderr
        return r

    def calls():
        path = standins / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def folders():
        return sorted(backups.glob("aisc-secrets-backup-*"))

    yield {"run": run, "calls": calls, "folders": folders, "backups": backups, "key": key, "postgres": postgres,
           "standins": standins}
    for text in outputs:
        assert PLANTED not in text and PASSPHRASE not in text


def applied(calls):
    return [c for c in calls if (c[0] == "engine" and c[1][:1] == ["apply"]) or (c[0] == "platform" and c[1][:1] == ["apply"])]


def test_without_arguments_it_is_a_dry_run(bed):
    r = bed["run"]()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [(c[0], c[1][:1]) for c in bed["calls"]()] == [("engine", ["count"]), ("platform", ["count"])]
    out = r.stdout
    assert out.index("== engine ==") < out.index(f"{PROJECT_DB}: aisc_backend_ledgeroutbox rows_to_mask=1")
    assert out.index("== platform ==") < out.index(f"project {PID}: core.outbox rows_to_mask=1")
    assert "Rotate these keys, they were stored in clear:" in out
    assert out.strip().splitlines()[-1] == "dry run: nothing changed. Run with --apply --backup-dir DIR to clean."
    assert bed["folders"]() == []
    assert not list(ROOT.glob("aisc-secrets-backup-*"))


def test_apply_needs_a_backup_folder(bed):
    r = bed["run"]("--apply")
    assert r.returncode == 2
    assert "--apply needs --backup-dir" in r.stdout + r.stderr
    assert bed["calls"]() == []


def test_the_backup_folder_must_be_outside_the_repository(bed):
    inside = ROOT / "scratch-backup"
    existed = inside.exists()
    try:
        r = bed["run"]("--apply", "--backup-dir", str(inside))
        assert r.returncode == 2
        assert "the backup folder must be outside the repository" in r.stdout + r.stderr
        assert not applied(bed["calls"]())
    finally:
        if not existed and inside.exists():
            shutil.rmtree(inside)


@pytest.mark.parametrize("passphrase", [None, "p" * 15])
def test_apply_needs_a_passphrase_of_16_characters(bed, passphrase):
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]), AISC_CLEANUP_BACKUP_PASSPHRASE=passphrase)
    assert r.returncode == 2
    assert "set AISC_CLEANUP_BACKUP_PASSPHRASE (16 characters or more) in this shell first" in r.stdout + r.stderr
    assert bed["folders"]() == []
    assert not applied(bed["calls"]())


def test_not_enough_disk_stops_before_the_backup(bed):
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]),
                   CLEAN_SECRETS_EXTRA_FREE_BYTES="1000000000000000000")
    assert r.returncode == 3, r.stdout + r.stderr
    assert any(line.startswith("not enough free disk") for line in (r.stdout + r.stderr).splitlines())
    assert bed["folders"]() == []
    assert not applied(bed["calls"]())


def test_nothing_to_clean_makes_no_backup(bed):
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]), STANDIN_ZEROS="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nothing to clean" in r.stdout
    assert bed["folders"]() == []
    assert not applied(bed["calls"]())


def _restored_table_data(postgres, path):
    """Decrypted into a pipe only, listed by pg_restore in the container: its TABLE DATA lines."""
    decrypt = subprocess.Popen(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "600000",
                                "-pass", "env:AISC_CLEANUP_BACKUP_PASSPHRASE", "-in", str(path)],
                               stdout=subprocess.PIPE, env={**os.environ, "AISC_CLEANUP_BACKUP_PASSPHRASE": PASSPHRASE})
    listed = subprocess.run(["docker", "exec", "-i", postgres, "pg_restore", "--list"], stdin=decrypt.stdout,
                            capture_output=True, text=True, timeout=120)
    decrypt.stdout.close()
    assert decrypt.wait() == 0
    assert listed.returncode == 0, listed.stderr
    return [line for line in listed.stdout.splitlines() if " TABLE DATA " in line]


def test_a_full_apply_keeping_the_backup(bed):
    r = bed["run"]("--apply", "--keep-backup", "--backup-dir", str(bed["backups"]))
    assert r.returncode == 0, r.stdout + r.stderr
    [folder] = bed["folders"]()
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    dumps = {p.name: p for p in folder.glob("*.dump.enc")}
    assert set(dumps) == {"platform.dump.enc", f"{PROJECT_DB}.dump.enc"}
    for path in dumps.values():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        data = path.read_bytes()
        assert PLANTED.encode() not in data and b'"api_key"' not in data
    assert len(_restored_table_data(bed["postgres"], dumps["platform.dump.enc"])) == PLATFORM_TABLES
    assert len(_restored_table_data(bed["postgres"], dumps[f"{PROJECT_DB}.dump.enc"])) == PROJECT_TABLES
    calls = bed["calls"]()
    assert [(c[0], c[1][:1]) for c in calls] == [
        ("engine", ["count"]), ("platform", ["count"]), ("engine", ["apply"]), ("platform", ["apply"]),
        ("engine", ["count"]), ("platform", ["count"]), ("platform", ["export"]), ("checker", calls[-1][1][:1])]
    assert calls[-2][1] == ["export", PID]
    checker = calls[-1]
    assert checker[1][:4] == ["--public-key", str(bed["key"]), "--project", PID] and checker[2] is True
    assert "backup kept at" in r.stdout
    assert "Rotate these keys, they were stored in clear:" in r.stdout
    assert not list(folder.glob("verify/*.jsonl"))          # each export is removed once checked
    removed = bed["run"]("--delete-backup", str(folder))
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert "backup deleted" in removed.stdout
    assert not folder.exists()


def test_a_full_apply_deletes_its_backup(bed):
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "backup deleted" in r.stdout
    assert bed["folders"]() == []


def test_a_failed_verification_keeps_the_backup(bed):
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]), STANDIN_CHECKER_EXIT="1")
    assert r.returncode == 1, r.stdout + r.stderr
    [folder] = bed["folders"]()
    assert f"backup kept at {folder}" in r.stdout + r.stderr


def test_a_failed_engine_step_stops_before_the_platform_and_keeps_the_backup(bed):
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]), STANDIN_ENGINE_APPLY_EXIT="1")
    assert r.returncode == 5, r.stdout + r.stderr
    assert not [c for c in bed["calls"]() if c[0] == "platform" and c[1][:1] == ["apply"]]
    [folder] = bed["folders"]()
    assert f"backup kept at {folder}" in r.stdout + r.stderr


def test_a_failed_backup_changes_nothing(bed):
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]),
                   CLEAN_SECRETS_PG_CONTAINER="aisc-t-no-such-container-" + uuid.uuid4().hex[:6])
    assert r.returncode == 4, r.stdout + r.stderr
    assert "backup failed; nothing changed" in r.stdout + r.stderr
    assert bed["folders"]() == []
    assert not applied(bed["calls"]())


def test_delete_backup_refuses_a_folder_that_is_not_a_backup(bed, tmp_path):
    other = tmp_path / "not-a-backup"
    other.mkdir()
    (other / "keep.txt").write_text("kept")
    r = bed["run"]("--delete-backup", str(other))
    assert r.returncode == 2
    assert (other / "keep.txt").exists()


def test_the_script_runs_on_bash_3_2():
    import test_bash32

    assert SCRIPT in test_bash32.scripts()
    found = []
    for n, line in enumerate(SCRIPT.read_text().splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for pattern, what in test_bash32.BASH4:
            if re.search(pattern, line):
                found.append(f"{n}: {what}")
    assert not found, found
    r = subprocess.run(["docker", "run", "--rm", "-v", f"{SCRIPT}:/w/clean-old-secrets.sh:ro", "bash:3.2",
                        "bash", "-n", "/w/clean-old-secrets.sh"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr


# Deleting what holds secrets: shred where it exists, rm (and say so) where it does not

SHRED = """\
#!/bin/sh
for f in "$@"; do
  case "$f" in -*) continue ;; esac
  echo "$f" >> "$STANDIN_DIR/shredded.txt"
  rm -f "$f"
done
"""


def test_every_backup_and_export_file_is_shredded(bed, tmp_path):
    tools = tmp_path / "shred-bin"
    tools.mkdir()
    (tools / "shred").write_text(SHRED)
    (tools / "shred").chmod(0o755)
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]),
                   PATH=f"{tools}{os.pathsep}{os.environ['PATH']}")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "backup deleted" in r.stdout
    log = bed["standins"] / "shredded.txt"
    shredded = log.read_text().splitlines() if log.exists() else []
    names = sorted(os.path.basename(path) for path in shredded)
    assert names == sorted([f"{PID}.jsonl", "platform.dump.enc", f"{PROJECT_DB}.dump.enc"]), names
    assert bed["folders"]() == []


def _path_without_shred(tmp_path):
    """A PATH folder linking every command on PATH but shred."""
    tools = tmp_path / "no-shred-bin"
    tools.mkdir()
    for folder in os.environ["PATH"].split(os.pathsep):
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            target = os.path.join(folder, name)
            if name == "shred" or (tools / name).exists() or not os.access(target, os.X_OK):
                continue
            (tools / name).symlink_to(target)
    return str(tools)


def test_without_shred_the_files_are_removed_and_the_output_says_so(bed, tmp_path):
    path = _path_without_shred(tmp_path)
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]), PATH=path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "backup deleted" in r.stdout
    assert bed["folders"]() == []
    said = (r.stdout + r.stderr).replace(str(tmp_path), "")         # the test's own folder names hold "shred"
    assert "shred" in said.lower(), "the output must say shred was not available"



# Kept text fields that may hold a key: named under their own heading, never under the keys to rotate; changed
# only with --scrub-config-text

ROTATE_HEADING = "Rotate these keys, they were stored in clear:"
REVIEW_HEADING = "Review these fields (text that may contain a key; not changed):"
REVIEW_LINE = f"{PROJECT_DB}: review plugin=aisc-plugin-b field=prompt configs=1"
TEXT_ROTATE_LINE = f"{PROJECT_DB}: rotate plugin=aisc-plugin-b field=prompt configs=1"


def _under(out, heading):
    """The rotate or review lines printed right under `heading` (empty when the heading is absent)."""
    lines = out.splitlines()
    if heading not in lines:
        return []
    found = []
    for line in lines[lines.index(heading) + 1:]:
        if not re.search(r": (rotate|review) ", line):
            break
        found.append(line)
    return found


def _engine_args(calls):
    return [c[1] for c in calls if c[0] == "engine"]


def test_the_dry_run_names_text_fields_for_review_apart_from_the_keys_to_rotate(bed):
    r = bed["run"]()
    assert r.returncode == 0, r.stdout + r.stderr
    assert _under(r.stdout, REVIEW_HEADING) == [REVIEW_LINE]
    rotate = _under(r.stdout, ROTATE_HEADING)
    assert rotate and not [line for line in rotate if ": review " in line]
    assert TEXT_ROTATE_LINE not in r.stdout
    assert all("--scrub-config-text" not in args for args in _engine_args(bed["calls"]()))


def test_apply_leaves_text_fields_and_names_them_for_review(bed):
    r = bed["run"]("--apply", "--backup-dir", str(bed["backups"]))
    assert r.returncode == 0, r.stdout + r.stderr
    tail = r.stdout[r.stdout.rindex("backup deleted"):]
    assert _under(tail, REVIEW_HEADING) == [REVIEW_LINE]
    assert not [line for line in _under(tail, ROTATE_HEADING) if ": review " in line]
    assert all("--scrub-config-text" not in args for args in _engine_args(bed["calls"]()))


def test_on_request_text_fields_are_scrubbed_and_named_to_rotate(bed):
    r = bed["run"]("--scrub-config-text")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [args for args in _engine_args(bed["calls"]())] == [["count", "--scrub-config-text"]]
    assert REVIEW_HEADING not in r.stdout
    assert TEXT_ROTATE_LINE in _under(r.stdout, ROTATE_HEADING)
    applied_run = bed["run"]("--apply", "--scrub-config-text", "--backup-dir", str(bed["backups"]))
    assert applied_run.returncode == 0, applied_run.stdout + applied_run.stderr
    engine = _engine_args(bed["calls"]())[1:]
    assert [args[0] for args in engine] == ["count", "apply", "count"]
    assert all("--scrub-config-text" in args for args in engine), engine


def test_the_runbook_says_when_to_scrub_config_text():
    text = (ROOT / "docs/runbooks/clean-old-secrets.md").read_text()
    assert "--scrub-config-text" in text
    assert "Review these fields" in text
