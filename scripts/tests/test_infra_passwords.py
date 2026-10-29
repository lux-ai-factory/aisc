"""No password of the running stack is one anyone with a clone knows, but the sign-in of a local install.

- The realm's two development accounts are admin / admin and user / user on a local install, where only this
  machine reaches the sign-in (Keycloak is published on 127.0.0.1). An install served to others
  (CADDY_DOMAIN https://) gets generated ones. Either way env.secrets holds them and the realm import takes
  them from there; the realm file holds no password of theirs.
- The tracked env file holds no infrastructure password: env.secrets does (scripts/secrets.sh).
- The checks sign in with the passwords env.secrets holds, never with a built-in one.
- scripts/rotate-infra-password.sh gives one infrastructure password a new value: in the service first,
  then in env.secrets and env.runtime, without the value ever on a command line of the host.
"""
import json
import os
import re
import shutil
import subprocess

import pytest
import yaml

from conftest import RUN_KCADM_IN_EXEC, ROOT, add_fake_kcadm, aisc_py, copy_install_scripts
from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture)
from test_llm_keys import secrets_of

SECRETS_SH = ROOT / "scripts/secrets.sh"
ROTATE = ROOT / "scripts/rotate-infra-password.sh"
ACCOUNTS = {"admin": "AISC_ADMIN_PASSWORD", "user": "AISC_USER_PASSWORD"}
ROTATABLE = ("POSTGRES_PASSWORD", "RABBITMQ_PASSWORD", "S3_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD",
             "AISC_ADMIN_PASSWORD", "AISC_USER_PASSWORD")
#: the passwords set through kcadm in Keycloak's container
KEYCLOAK_SET = ("KEYCLOAK_ADMIN_PASSWORD", "AISC_ADMIN_PASSWORD", "AISC_USER_PASSWORD")


def test_secrets_makes_the_accounts_passwords_and_keeps_them_like_the_other_volume_bound_ones():
    install = aisc_py()
    for name in ACCOUNTS.values():
        assert dict(install.SECRETS)[name] == "account", name
        assert name in install.VOLUME_BOUND, name


def _accounts_of_a_new_install(scratch, caddy_domain=None):  # noqa: F811
    env = {**os.environ}
    env.pop("CADDY_DOMAIN", None)
    if caddy_domain is not None:
        env["CADDY_DOMAIN"] = caddy_domain
    r = subprocess.run(["bash", str(scratch / "scripts/secrets.sh")], cwd=scratch, env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return {k: v for k, v in secrets_of(scratch).items() if k in ACCOUNTS.values()}


def test_a_local_install_signs_in_as_admin_admin_and_user_user(scratch):  # noqa: F811
    assert _accounts_of_a_new_install(scratch) == {"AISC_ADMIN_PASSWORD": "admin", "AISC_USER_PASSWORD": "user"}


def test_an_install_served_over_https_gets_generated_account_passwords(scratch):  # noqa: F811
    values = _accounts_of_a_new_install(scratch, "https://aisc.example.org")
    assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in values.values()), "not generated"


def test_the_tracked_https_domain_counts_as_well(scratch):  # noqa: F811
    env_file = scratch / "env.plugin_downloader"
    env_file.write_text(env_file.read_text().replace('CADDY_DOMAIN="http://localhost"', 'CADDY_DOMAIN="https://aisc.example.org"'))
    values = _accounts_of_a_new_install(scratch)
    assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in values.values()), "not generated"


def test_an_existing_install_keeps_the_account_passwords_its_realm_holds(scratch):  # noqa: F811
    (scratch / "env.secrets").write_text("AISC_ADMIN_PASSWORD=" + "a" * 64 + "\nAISC_USER_PASSWORD=" + "b" * 64 + "\n")
    assert _accounts_of_a_new_install(scratch) == {"AISC_ADMIN_PASSWORD": "a" * 64, "AISC_USER_PASSWORD": "b" * 64}


def test_the_realm_file_holds_no_password_of_its_accounts():
    realm = json.loads((ROOT / "keycloak/aisc-realm.json").read_text())
    users = {u["username"]: u for u in realm["users"]}
    for username, name in ACCOUNTS.items():
        creds = users[username]["credentials"]
        assert creds == [{"type": "password", "value": "${" + name + "}", "temporary": False}], username


def test_keycloak_is_given_the_accounts_passwords_and_refuses_to_start_without_them():
    keycloak = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]["keycloak"]
    env = keycloak["environment"]
    for name in (*ACCOUNTS.values(), "KEYCLOAK_ADMIN_PASSWORD"):
        target = "KC_BOOTSTRAP_ADMIN_PASSWORD" if name == "KEYCLOAK_ADMIN_PASSWORD" else name
        assert re.fullmatch(r"\$\{" + name + r":\?[^}]+\}", env[target]), target


def test_the_tracked_env_file_holds_no_infrastructure_password():
    lines = (ROOT / "env.plugin_downloader").read_text().splitlines()
    for name in ("POSTGRES_PASSWORD", "RABBITMQ_PASSWORD", "S3_PASSWORD"):
        [line] = [line for line in lines if line.startswith(name + "=")]
        assert line == name + "=", name


CHECKS = ["scripts/verify-sso.sh", "scripts/verify-rbac.sh", "scripts/verify-project-databases.sh",
          "scripts/verify-plugins.sh", "scripts/lib/gateway-session.sh"]


@pytest.mark.parametrize("path", CHECKS)
def test_no_check_signs_in_with_a_built_in_password(path):
    text = (ROOT / path).read_text()
    for pattern in (r"\b(admin admin|user user)\b", r"""get\(["']\w*PASS\w*["'], ["'](admin|user)["']""",
                    r"PASS\w*:-(admin|user)\}", r"default (user / user|admin / admin)"):
        assert not re.search(pattern, text), (path, pattern)


def test_the_checks_read_the_accounts_passwords_from_env_secrets():
    lib = (ROOT / "scripts/lib/dev-accounts.sh").read_text()
    assert "env.secrets" in lib and "AISC_ADMIN_PASSWORD" in lib and "AISC_USER_PASSWORD" in lib
    for path in CHECKS[:4]:
        assert "lib/dev-accounts.sh" in (ROOT / path).read_text(), path


# scripts/rotate-infra-password.sh, against a copy of the repo's env files and a docker that only records

FAKE_DOCKER = """#!/usr/bin/env bash
{ printf 'ARGV'; printf ' %q' "$@"; printf '\\n'; env | sed -n 's/^\\(NEW_VALUE\\|OLD_VALUE\\|ADMIN_VALUE\\|KC_CLI_PASSWORD\\)=/ENV \\1=/p'; } >> "$DOCKER_LOG"
""" + RUN_KCADM_IN_EXEC + """
cat > /dev/null
# this project's Keycloak container, as compose ps -q names it (FAKE_KEYCLOAK_ID="": none running)
[[ "$*" == *" ps -q keycloak"* ]] && printf '%s\n' "${FAKE_KEYCLOAK_ID-kc-of-this-project}"
[[ "$*" == *" ps -q postgres"* ]] && printf '%s\n' "${FAKE_POSTGRES_ID-pg-of-this-project}"
[[ "$*" == *" ps -q rabbitmq"* ]] && printf '%s\n' "${FAKE_RABBITMQ_ID-mq-of-this-project}"
exit 0
"""


@pytest.fixture
def install(tmp_path):
    copy_install_scripts(tmp_path)
    shutil.copy2(ROOT / "env.plugin_downloader", tmp_path / "env.plugin_downloader")
    # served over https, so every password is generated: a check that an old value never reaches a command
    # line means nothing for a value as common as "admin"
    subprocess.run(["bash", "scripts/secrets.sh"], cwd=tmp_path, check=True, capture_output=True,
                   env={**os.environ, "CADDY_DOMAIN": "https://aisc.example.org"})
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    add_fake_kcadm(bin_dir)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "DOCKER_LOG": str(tmp_path / "docker.log")}
    return tmp_path, env


def values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


@pytest.mark.parametrize("name", ROTATABLE)
def test_rotating_one_password_changes_it_in_the_service_then_in_both_env_files_and_nothing_else(install, name):
    root, env = install
    before = values(root / "env.secrets")
    r = subprocess.run(["bash", "scripts/rotate-infra-password.sh", name], cwd=root, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    after = values(root / "env.secrets")
    assert after[name] != before[name] and len(after[name]) >= 32
    assert {k: v for k, v in after.items() if k != name} == {k: v for k, v in before.items() if k != name}
    assert values(root / "env.runtime")[name] == after[name]
    log = (root / "docker.log").read_text() if (root / "docker.log").exists() else ""
    # the new value reaches the service by name, never in an argument
    assert after[name] not in "".join(line for line in log.splitlines() if line.startswith("ARGV"))
    assert before[name] not in "".join(line for line in log.splitlines() if line.startswith("ARGV"))
    assert after[name] not in r.stdout + r.stderr
    if name in KEYCLOAK_SET:   # kcadm reads it as JSON on stdin
        assert json.loads((root / "exec-input").read_text())["value"] == after[name]
    elif name != "S3_PASSWORD":  # MinIO takes its root password from its environment when it is recreated
        assert f"ENV NEW_VALUE={after[name]}" in log


def test_rotating_refuses_a_name_it_does_not_know(install):
    root, env = install
    before = (root / "env.secrets").read_text()
    r = subprocess.run(["bash", "scripts/rotate-infra-password.sh", "DJANGO_SECRET_KEY"], cwd=root, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert (root / "env.secrets").read_text() == before


def test_a_service_that_refuses_the_change_leaves_env_secrets_as_it_was(install):
    root, env = install
    (root / "bin/docker").write_text("#!/usr/bin/env bash\nexit 1\n")
    before = (root / "env.secrets").read_text()
    r = subprocess.run(["bash", "scripts/rotate-infra-password.sh", "POSTGRES_PASSWORD"], cwd=root, env=env,
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert (root / "env.secrets").read_text() == before


@pytest.mark.parametrize("path", ["README.md", "scripts/aisc.py"])
def test_the_first_sign_in_names_admin_admin_and_where_a_server_install_keeps_its_password(path):
    """A local install signs in as admin / admin; one served over https has generated passwords, read
    from env.secrets."""
    text = (ROOT / path).read_text()
    assert re.search(r"admin`? ?/ ?`?admin", text), path
    assert "AISC_ADMIN_PASSWORD" in text and "env.secrets" in text and "https" in text, path


# --ask: a password the person chooses, read without echo (from stdin here, as when it is not a terminal)

def ask(install, name, typed):
    root, env = install
    return subprocess.run(["bash", "scripts/rotate-infra-password.sh", name, "--ask"], cwd=root, env=env,
                          input=typed, capture_output=True, text=True)


def test_a_chosen_password_is_set_in_the_service_and_both_env_files(install):
    root, _ = install
    chosen = "Correct-horse-battery-9"
    r = ask(install, "AISC_ADMIN_PASSWORD", chosen + "\n")
    assert r.returncode == 0, r.stderr
    assert values(root / "env.secrets")["AISC_ADMIN_PASSWORD"] == chosen
    assert values(root / "env.runtime")["AISC_ADMIN_PASSWORD"] == chosen
    log = (root / "docker.log").read_text()
    assert json.loads((root / "exec-input").read_text())["value"] == chosen
    assert chosen not in "".join(line for line in log.splitlines() if line.startswith("ARGV"))
    assert chosen not in r.stdout + r.stderr


@pytest.mark.parametrize("typed", ["short-9", "has space in it", "dollar$sign-long", "hash#sign-long1",
                                   "quote'sign-long1", 'dquote"sign-long', "back\\slash-long1", ""])
def test_a_chosen_password_the_env_file_could_not_hold_is_refused(install, typed):
    root, _ = install
    before = (root / "env.secrets").read_text()
    r = ask(install, "AISC_ADMIN_PASSWORD", typed + "\n")
    assert r.returncode == 2, r.stderr
    assert (root / "env.secrets").read_text() == before
    assert not (root / "docker.log").exists()


def test_a_keycloak_password_is_set_in_this_project_s_keycloak_and_no_other(install):
    """A second copy beside an install renames its containers: the bare name keycloak is the other install's."""
    root, env = install
    r = subprocess.run(["bash", "scripts/rotate-infra-password.sh", "AISC_USER_PASSWORD"], cwd=root, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    execs = [line for line in (root / "docker.log").read_text().splitlines() if line.startswith("ARGV exec ")]
    # the account's id, then its new password
    assert len(execs) == 2 and all(" kc-of-this-project bash " in e and " keycloak bash " not in e for e in execs)


def test_a_keycloak_password_is_not_changed_when_this_project_runs_no_keycloak(install):
    root, env = install
    before = (root / "env.secrets").read_text()
    r = subprocess.run(["bash", "scripts/rotate-infra-password.sh", "AISC_USER_PASSWORD"], cwd=root,
                       env={**env, "FAKE_KEYCLOAK_ID": ""}, capture_output=True, text=True)
    assert r.returncode != 0
    assert "Keycloak" in r.stderr
    assert (root / "env.secrets").read_text() == before
    assert not [line for line in (root / "docker.log").read_text().splitlines() if line.startswith("ARGV exec ")]


IN_ITS_OWN_VOLUME = {"POSTGRES_PASSWORD": ("postgres", "pg-of-this-project", "FAKE_POSTGRES_ID"),
                     "RABBITMQ_PASSWORD": ("rabbitmq", "mq-of-this-project", "FAKE_RABBITMQ_ID")}


@pytest.mark.parametrize("name", IN_ITS_OWN_VOLUME)
def test_a_postgres_or_rabbitmq_password_is_set_in_this_project_s_container_and_no_other(install, name):
    """The bare name postgres or rabbitmq is an older install's container, which may be the one running."""
    root, env = install
    service, container, _ = IN_ITS_OWN_VOLUME[name]
    stack = "aisc-" + values(root / "env.secrets")["AISC_INSTALL"]
    r = subprocess.run(["bash", "scripts/rotate-infra-password.sh", name], cwd=root, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    log = (root / "docker.log").read_text().splitlines()
    assert [line for line in log if line.startswith("ARGV compose -p " + stack) and line.endswith(" ps -q " + service)]
    execs = [line for line in log if line.startswith("ARGV exec ")]
    assert len(execs) == 1 and f" {container} sh " in execs[0] and f" {service} sh " not in execs[0]


@pytest.mark.parametrize("name", IN_ITS_OWN_VOLUME)
def test_a_postgres_or_rabbitmq_password_is_not_changed_when_this_project_runs_no_such_container(install, name):
    root, env = install
    service, _, unset = IN_ITS_OWN_VOLUME[name]
    before = (root / "env.secrets").read_text()
    r = subprocess.run(["bash", "scripts/rotate-infra-password.sh", name], cwd=root, env={**env, unset: ""},
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert f"ps {service}" in r.stderr and "nothing changed" in r.stderr
    assert (root / "env.secrets").read_text() == before
    assert not [line for line in (root / "docker.log").read_text().splitlines() if line.startswith("ARGV exec ")]


@pytest.mark.parametrize("name", KEYCLOAK_SET)
def test_no_secret_reaches_a_command_line_when_kcadm_sets_a_password(install, name):
    """Neither docker's command line on the host nor kcadm's inside the container (which the host's `ps`
    shows too): Keycloak's admin password reaches kcadm through KC_CLI_PASSWORD, the new one as JSON on stdin."""
    root, env = install
    before = values(root / "env.secrets")
    r = subprocess.run(["bash", "scripts/rotate-infra-password.sh", name], cwd=root, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    after = values(root / "env.secrets")
    secrets = {v for v in (*before.values(), *after.values()) if len(v) >= 8}
    argv = "".join(line for line in (root / "docker.log").read_text().splitlines() if line.startswith("ARGV"))
    assert not [v for v in secrets if v in argv]
    assert not [v for v in secrets if v in (root / "kcadm.log").read_text()]
    assert (root / "kcadm-login").read_text().splitlines() == [before["KEYCLOAK_ADMIN_PASSWORD"]] * 2
    account = {"KEYCLOAK_ADMIN_PASSWORD": "admin", "AISC_ADMIN_PASSWORD": "admin", "AISC_USER_PASSWORD": "user"}[name]
    realm = "master" if name == "KEYCLOAK_ADMIN_PASSWORD" else "aisc"
    calls = (root / "kcadm.log").read_text()
    assert f"get users -r {realm} -q username={account}" in calls
    assert f"update users/id-of-{account}/reset-password -r {realm} -f -" in calls
    assert json.loads((root / "exec-input").read_text()) == {"type": "password", "value": after[name],
                                                              "temporary": False}
