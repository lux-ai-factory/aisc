"""The add-controls service (apps/add-controls-catalogue, lux-ai-factory/aisc-add-controls-catalogue): an admin
publishes the organisation's own checklists into the org_controls volume, which the platform reads read-only as
ORG_CONTROLS_DIR (local_controls/README.md). It runs only under the compose profile `add-controls`, so a stack
that does not enable it is unchanged; Caddy serves it at the launcher's /add-controls/ without the sign-in
gateway (the app has its own login); scripts/secrets.sh makes its Django secret and nothing else of it.

Read-only: the compose files are resolved with `docker compose config` from scratch copies, secrets.sh runs on
a scratch copy; nothing is started, stopped or built.

    uv run --no-project --with pytest --with pyyaml python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_add_controls.py
"""

import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of

FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]
#: an admin's hash as `manage.py hash_password` prints it: `$` everywhere, which compose would expand
HASH = "pbkdf2_sha256$1000000$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaGhhc2g="


def config(tmp_path, *profile, extra_env=""):
    args, required = [], set()
    for f in FILES:
        shutil.copy(ROOT / f, tmp_path / f)
        args += ["-f", str(tmp_path / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env_file = tmp_path / "env"
    env_file.write_text((ROOT / "env.development").read_text() + "\n" + extra_env)
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("ADD_CONTROLS_")},
           **{k: "dummy" for k in required}}
    base = ["docker", "compose", "-p", "aisc-t-addctl", "--project-directory", str(ROOT),
            "--env-file", str(env_file), *args]
    if profile:
        base += ["--profile", profile[0]]
    r = subprocess.run(base + ["config", "--format", "json"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    return config(tmp_path_factory.mktemp("plain"))


@pytest.fixture(scope="module")
def with_profile(tmp_path_factory):
    filled = (f"ADD_CONTROLS_DJANGO_SECRET_KEY=s3cret\nADD_CONTROLS_ADMIN_USERNAME=admin\n"
              f"ADD_CONTROLS_ADMIN_PASSWORD_HASH='{HASH}'\nADD_CONTROLS_LLM_MODEL=mistral-large-latest\n"
              f"ADD_CONTROLS_LLM_MISTRAL_KEY=mk\n")
    return config(tmp_path_factory.mktemp("profile"), "add-controls", extra_env=filled)


# ── compose ─────────────────────────────────────────────────────────────────

def test_the_platform_reads_the_org_folder_read_only(plain):
    mounts = [(v.get("type"), v.get("source"), v.get("target"), v.get("read_only"))
              for v in plain["services"]["platform"]["volumes"]]
    assert ("volume", "org_controls", "/app/org_controls", True) in mounts, mounts
    assert "org_controls" in plain["volumes"]


def test_without_the_profile_there_is_no_add_controls_service(plain):
    assert "add-controls" not in plain["services"]


def test_without_the_profile_and_without_its_settings_the_config_is_valid(tmp_path):
    """An install whose env.runtime predates the service (no ADD_CONTROLS_*) still resolves, profile or not:
    nothing of it is required by compose; the app names a missing setting itself at start."""
    assert "add-controls" not in config(tmp_path)["services"]
    (tmp_path / "p").mkdir()
    assert "add-controls" in config(tmp_path / "p", "add-controls")["services"]


def test_the_service_is_built_from_the_submodule_under_its_profile(with_profile):
    svc = with_profile["services"]["add-controls"]
    assert svc.get("profiles") == ["add-controls"]
    ctx = svc["build"]["context"] if isinstance(svc.get("build"), dict) else svc["build"]
    assert str(ctx).rstrip("/").endswith("apps/add-controls-catalogue")
    assert svc.get("pull_policy") == "never" and svc.get("image", "").startswith("aisc-add-controls:")
    assert "frontend" in (svc.get("networks") or {})


def test_the_service_publishes_into_the_volume_the_platform_reads(with_profile):
    svc = with_profile["services"]["add-controls"]
    env = svc.get("environment") or {}
    assert env.get("CATALOGUE_TARGET") == "local"
    assert env.get("LOCAL_CONTROLS_OUT_DIR") == "/out"
    assert env.get("APP_BASE_PATH") == "/add-controls"
    mounts = [(v.get("type"), v.get("source"), v.get("target"), bool(v.get("read_only"))) for v in svc["volumes"]]
    assert ("volume", "org_controls", "/out", False) in mounts, mounts
    assert any(t == "volume" and tgt == "/data" for t, _, tgt, _ in mounts), "drafts and audit log need /data"


def test_its_settings_come_from_env_secrets_under_the_apps_names(with_profile):
    env = with_profile["services"]["add-controls"].get("environment") or {}
    assert env.get("DJANGO_SECRET_KEY") == "s3cret"
    assert env.get("ADMIN_USERNAME") == "admin"
    assert env.get("ADMIN_PASSWORD_HASH") == HASH, "the hash's `$` must reach the app as written"
    assert env.get("LLM_MODEL") == "mistral-large-latest"
    assert env.get("LLM_MISTRAL_KEY") == "mk"
    assert {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"} <= set(env)


def test_the_local_stack_is_plain_http_so_its_cookies_are_not_secure(with_profile):
    """CADDY_DOMAIN is http://localhost: a Secure cookie would never come back and the login would loop."""
    assert 'CADDY_DOMAIN="http://' in (ROOT / "env.plugin_downloader").read_text()
    env = with_profile["services"]["add-controls"].get("environment") or {}
    assert env.get("INSECURE_COOKIES") == "true"
    assert "http://localhost:8100" in env.get("CSRF_TRUSTED_ORIGINS", "")
    assert "localhost" in env.get("ALLOWED_HOSTS", "").split(",")


# ── Caddy ───────────────────────────────────────────────────────────────────

def _launcher_handle(path):
    text = (ROOT / "Caddyfile").read_text()
    launcher = text[text.index("{$CADDY_DOMAIN}:{$HOMEPAGE_PORT}"):text.index("{$CADDY_DOMAIN}:{$DASHBOARD_PORT}")]
    m = re.search(r"^(\s*)handle " + re.escape(path) + r" \{\n(.*?)^\1\}", launcher, re.M | re.S)
    assert m, f"the launcher has no `handle {path}`"
    return launcher, m.group(2)


def test_caddy_serves_the_app_at_its_prefix_unstripped_and_without_the_sign_in():
    launcher, body = _launcher_handle("/add-controls/*")
    lines = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("#")]
    assert lines == ["reverse_proxy add-controls:8000"], lines
    assert "redir /add-controls /add-controls/" in launcher
    assert "handle_path /add-controls" not in launcher


def test_the_add_controls_route_comes_before_the_launchers_catch_all():
    launcher, _ = _launcher_handle("/add-controls/*")
    assert launcher.index("handle /add-controls/*") < launcher.rindex("    handle {")


# ── secrets.sh ──────────────────────────────────────────────────────────────

def test_secrets_makes_the_django_secret_only(scratch):  # noqa: F811
    run_secrets(scratch)
    values = secrets_of(scratch)
    assert re.fullmatch(r"[0-9a-f]{64}", values.get("ADD_CONTROLS_DJANGO_SECRET_KEY", ""))
    for never in ("ADD_CONTROLS_ADMIN_USERNAME", "ADD_CONTROLS_ADMIN_PASSWORD_HASH", "ADD_CONTROLS_LLM_MODEL",
                  "ADD_CONTROLS_LLM_MISTRAL_KEY", "ADD_CONTROLS_OPENAI_API_KEY", "ADD_CONTROLS_ANTHROPIC_API_KEY"):
        assert never not in values, f"{never} is the admin's to fill in, never generated"


def test_an_existing_env_secrets_gets_the_django_secret_added(scratch):  # noqa: F811
    run_secrets(scratch)
    path = scratch / "env.secrets"
    path.write_text("".join(l + "\n" for l in path.read_text().splitlines()
                            if not l.startswith("ADD_CONTROLS_DJANGO_SECRET_KEY=")))
    run_secrets(scratch)
    assert re.fullmatch(r"[0-9a-f]{64}", secrets_of(scratch).get("ADD_CONTROLS_DJANGO_SECRET_KEY", ""))


def test_what_the_admin_filled_in_survives_a_run_and_a_rotate(scratch):  # noqa: F811
    """The admin's username, hash, model and key are written into env.secrets by hand: a plain run keeps them
    (it only appends), and --rotate, which rebuilds the file from the generated list, carries them over."""
    run_secrets(scratch)
    filled = {"ADD_CONTROLS_ADMIN_USERNAME": "admin", "ADD_CONTROLS_ADMIN_PASSWORD_HASH": f"'{HASH}'",
              "ADD_CONTROLS_LLM_MODEL": "gpt-4o", "ADD_CONTROLS_OPENAI_API_KEY": "sk-test"}
    with (scratch / "env.secrets").open("a") as f:
        f.writelines(f"{k}={v}\n" for k, v in filled.items())
    run_secrets(scratch)
    assert {k: secrets_of(scratch).get(k) for k in filled} == filled
    before = secrets_of(scratch)["ADD_CONTROLS_DJANGO_SECRET_KEY"]
    r = subprocess.run(["bash", str(scratch / "scripts/secrets.sh"), "--rotate"], cwd=scratch,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    after = secrets_of(scratch)
    assert {k: after.get(k) for k in filled} == filled, "--rotate dropped what the admin filled in"
    assert after["ADD_CONTROLS_DJANGO_SECRET_KEY"] != before, "the Django secret is an ordinary secret: rotated"
    runtime = (scratch / "env.runtime").read_text()
    assert f"ADD_CONTROLS_ADMIN_PASSWORD_HASH='{HASH}'" in runtime


# ── the catalogue no longer runs in the stack ───────────────────────────────

def test_verify_runs_no_catalogue_backend_suite():
    text = (ROOT / "scripts/verify.sh").read_text()
    assert "catalogue backend|" not in text and "apps/catalogue/backend" not in text


def test_verify_one_database_has_no_catalogue_migration_check():
    text = (ROOT / "scripts/verify-one-database.sh").read_text()
    assert "alembic" not in text and "docker exec catalogue-backend" not in text
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts/verify-one-database.sh")]).returncode == 0


def test_no_comment_points_at_the_removed_catalogue_backend_seed():
    found = []
    for path in [*(ROOT / "platform/platform_service").rglob("*.py"), *(ROOT / "platform/tests").rglob("*.py"),
                 ROOT / "local_controls/README.md"]:
        if "apps/catalogue/backend" in path.read_text():
            found.append(str(path.relative_to(ROOT)))
    assert not found, found


def test_the_readme_documents_the_organisation_folder():
    text = (ROOT / "local_controls/README.md").read_text()
    for needed in ("ORG_CONTROLS_DIR", "/app/org_controls", "add-controls", "_published_by", "env.secrets"):
        assert needed in text, needed
