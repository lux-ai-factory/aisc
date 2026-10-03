"""Where the keys live: the `llm` schema of each project database,
Fernet at rest and rotation.

Runs against the throwaway database. For the read-rights tests the throwaway also needs report_ro
and inspector_ro (init/report-roles.sql, init/inspector-role.sql); a role
that is missing there is skipped rather than failed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg.conninfo import make_conninfo

from platform_service import db, projectdb
from tests.conftest import needs_database
from tests.llm_support import INTERNAL_TOKEN, RISK_TOKEN, SECRETS_KEY, new_key

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"
PLATFORM_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_FILE = projectdb.TEMPLATE / "0005_llm.sql"


@pytest.fixture(autouse=True)
def _secrets(monkeypatch):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CARD_AGENT_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setenv("PLATFORM_RISK_MAPPER_TOKEN", RISK_TOKEN)
    monkeypatch.delenv("PLATFORM_INTERNAL_TOKEN", raising=False)


@pytest.fixture
def admin(as_user):
    return as_user("root", roles=("admin",))


@pytest.fixture
def project(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("llmdb")}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    return made.json()


def connect(dsn, project, role=None):
    name = projectdb.database_name(project["pid"])
    if role is None:
        return psycopg.connect(make_conninfo(dsn, dbname=name))
    return psycopg.connect(make_conninfo(dsn, dbname=name, user=role, password=role), autocommit=True)


def one(dsn, project, sql, params=()):
    with connect(dsn, project) as conn:
        return conn.execute(sql, params).fetchone()


def columns(dsn, project, table):
    with connect(dsn, project) as conn:
        return {r[0]: (r[1], r[2]) for r in conn.execute(
            "select column_name, data_type, is_nullable from information_schema.columns"
            " where table_schema = 'llm' and table_name = %s", (table,)).fetchall()}


# The template file


def test_s1_4_the_template_file_exists_and_is_idempotent_sql():
    assert TEMPLATE_FILE.is_file(), "missing platform/project-template/0005_llm.sql"
    text = TEMPLATE_FILE.read_text()
    creates = re.findall(r"\bCREATE\s+(?:SCHEMA|TABLE|INDEX|UNIQUE\s+INDEX)\b(?!\s+IF\s+NOT\s+EXISTS)", text, re.I)
    assert creates == [], f"CREATE without IF NOT EXISTS: {creates}"
    # it runs inside migrate()'s transaction: no transaction control of its own
    assert not re.search(r"^\s*(BEGIN|COMMIT|ROLLBACK)\s*;", text, re.I | re.M)


def test_s1_4_applying_the_file_again_changes_nothing(project, dsn):
    with connect(dsn, project) as conn:
        with conn.transaction():
            conn.execute(TEMPLATE_FILE.read_text())
            conn.execute(TEMPLATE_FILE.read_text())


def test_s1_1_schema_llm_is_owned_by_platform_rw_and_closed_to_everyone_else(project, dsn):
    owner, acl = one(dsn, project,
                     "select pg_get_userbyid(nspowner), nspacl::text from pg_namespace where nspname = 'llm'")
    assert owner == "platform_rw"
    grantees = set(re.findall(r'(?:^|[{,])"?([^=,{}"]*)=', acl or ""))
    assert grantees <= {"platform_rw"}, f"llm schema ACL grants others: {acl}"
    for role in ("controls_rw", "dashboard_ro", "public"):
        if role == "public":
            continue
        exists = one(dsn, project, "select 1 from pg_roles where rolname = %s", (role,))
        if exists:
            usage = one(dsn, project, "select has_schema_privilege(%s, 'llm', 'USAGE')", (role,))[0]
            assert usage is False, role


def test_s1_2_llm_provider_has_exactly_the_specified_columns(project, dsn):
    cols = columns(dsn, project, "provider")
    assert cols == {
        "provider": ("text", "NO"),
        "ciphertext": ("text", "YES"),
        "base_url": ("text", "YES"),
        "updated_at": ("timestamp with time zone", "NO"),
        "updated_by": ("text", "YES"),
    }
    pk = one(dsn, project, "select a.attname from pg_index i join pg_attribute a on a.attrelid = i.indrelid"
                           " and a.attnum = any(i.indkey) where i.indrelid = 'llm.provider'::regclass"
                           " and i.indisprimary")
    assert pk == ("provider",)


@pytest.mark.parametrize("bad", ["OpenAI", "a", "open-ai", "x" * 21, "", "open ai"])
def test_s1_2_the_provider_id_is_checked(project, dsn, bad):
    with connect(dsn, project) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into llm.provider (provider) values (%s)", (bad,))


def test_s1_3_llm_system_choice_has_exactly_the_specified_columns(project, dsn):
    assert columns(dsn, project, "system_choice") == {
        "system": ("text", "NO"),
        "provider": ("text", "NO"),
        "model": ("text", "NO"),
        "updated_at": ("timestamp with time zone", "NO"),
        "updated_by": ("text", "YES"),
    }


def test_s1_3_system_and_model_are_checked_and_the_provider_is_restricted(project, dsn):
    with connect(dsn, project) as conn:
        conn.execute("insert into llm.provider (provider) values ('ollama')")
        conn.execute("insert into llm.system_choice (system, provider, model) values ('card_agent', 'ollama', 'm')")
        for sql, params, err in [
            ("insert into llm.system_choice (system, provider, model) values ('telepathy', 'ollama', 'm')", (),
             psycopg.errors.CheckViolation),
            ("insert into llm.system_choice (system, provider, model) values ('risk_mapper', 'ollama', '')", (),
             psycopg.errors.CheckViolation),
            ("insert into llm.system_choice (system, provider, model) values ('risk_mapper', 'ollama', %s)",
             ("m" * 201,), psycopg.errors.CheckViolation),
            ("insert into llm.system_choice (system, provider, model) values ('risk_mapper', 'openai', 'm')", (),
             psycopg.errors.ForeignKeyViolation),
            ("delete from llm.provider where provider = 'ollama'", (), psycopg.errors.ForeignKeyViolation),
        ]:
            with pytest.raises(err):
                with conn.transaction():
                    conn.execute(sql, params)
        conn.rollback()


# Existing and new projects get it


def test_s1_5_a_new_project_gets_the_llm_tables_at_creation(project, dsn):
    assert one(dsn, project, "select to_regclass('llm.provider'), to_regclass('llm.system_choice')") == (
        "llm.provider", "llm.system_choice")
    assert one(dsn, project, "select 1 from provision.template_migration where name = '0005_llm.sql'")


def test_s1_5_a_project_made_before_0005_gets_it_at_the_first_query_after_start(
        client, as_user, unique, dsn, monkeypatch, tmp_path):
    old = tmp_path / "template"
    old.mkdir()
    for f in sorted(projectdb.TEMPLATE.glob("*.sql")):
        if f.name < "0005":
            shutil.copy(f, old / f.name)
    real = projectdb.TEMPLATE
    monkeypatch.setattr(projectdb, "TEMPLATE", old)
    made = client.post("/projects", json={"name": unique("pre5")}, headers=as_user(ALICE)).json()
    assert one(dsn, made, "select to_regnamespace('llm')") == (None,)

    monkeypatch.setattr(projectdb, "TEMPLATE", real)
    monkeypatch.setattr(db, "_unprovisioned", None)   # as at start: provision_all runs again
    db.pool()
    assert one(dsn, made, "select to_regclass('llm.provider')") == ("llm.provider",)


def test_s1_5_deleting_a_project_drops_its_keys_with_its_database(client, admin, project, dsn):
    assert client.put(f"/projects/{project['slug']}/llm/providers/openai", json={"api_key": new_key()},
                      headers=admin).status_code == 200
    r = client.request("DELETE", f"/projects/{project['slug']}", json={"confirm_name": project["name"]},
                       headers=admin)
    assert r.status_code == 204
    with psycopg.connect(dsn) as conn:
        assert conn.execute("select 1 from pg_database where datname = %s",
                            (projectdb.database_name(project["pid"]),)).fetchone() is None


# Who can read it


@pytest.mark.parametrize("role", ["controls_rw", "dashboard_ro", "report_ro"])
def test_s1_6_module_roles_cannot_read_the_llm_tables(project, dsn, role):
    try:
        conn = connect(dsn, project, role)
    except psycopg.OperationalError as exc:
        if "does not exist" in str(exc) or "password authentication" in str(exc):
            pytest.skip(f"{role} is not in this throwaway database")
        raise
    with conn:
        assert one(dsn, project, "select to_regclass('llm.provider')") == ("llm.provider",)
        for table in ("llm.provider", "llm.system_choice"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"select * from {table}")


def test_s1_6_the_inspector_reads_only_ciphertext(client, admin, project, dsn):
    key = new_key()
    assert client.put(f"/projects/{project['slug']}/llm/providers/openai", json={"api_key": key},
                      headers=admin).status_code == 200
    try:
        conn = connect(dsn, project, "inspector_ro")
    except psycopg.OperationalError:
        pytest.skip("inspector_ro is not in this throwaway database (apply init/inspector-role.sql)")
    with conn:
        found = conn.execute("select row_to_json(p)::text from llm.provider p").fetchall()
    assert found and all(key not in r[0] for r in found)


# Fernet at rest


def test_s5_2_s2_11_only_fernet_ciphertext_is_stored(client, admin, project, dsn):
    key = new_key()
    assert client.put(f"/projects/{project['slug']}/llm/providers/openai", json={"api_key": key},
                      headers=admin).status_code == 200
    with connect(dsn, project) as conn:
        dumped = [r[0] for r in conn.execute("select row_to_json(p)::text from llm.provider p").fetchall()]
        dumped += [r[0] for r in conn.execute("select row_to_json(s)::text from llm.system_choice s").fetchall()]
        token = conn.execute("select ciphertext from llm.provider where provider = 'openai'").fetchone()[0]
    assert all(key not in d and key[8:] not in d for d in dumped)
    assert Fernet(SECRETS_KEY.encode()).decrypt(token.encode()).decode() == key


def test_s2_11_the_newest_key_encrypts_and_older_ones_still_decrypt(client, admin, project, dsn, monkeypatch):
    older = Fernet.generate_key().decode()
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", older)
    first = new_key()
    client.put(f"/projects/{project['slug']}/llm/providers/openai", json={"api_key": first}, headers=admin)
    client.put(f"/projects/{project['slug']}/llm/systems/card_agent",
               json={"provider": "openai", "model": "gpt-a"}, headers=admin)
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", f"{SECRETS_KEY},{older}")
    r = client.get(f"/internal/projects/{project['pid']}/llm/card_agent",
                   headers={"X-AISC-Service-Token": INTERNAL_TOKEN})
    assert r.status_code == 200 and r.json()["api_key"] == first
    second = new_key()
    client.put(f"/projects/{project['slug']}/llm/providers/openai", json={"api_key": second}, headers=admin)
    token = one(dsn, project, "select ciphertext from llm.provider where provider = 'openai'")[0]
    assert Fernet(SECRETS_KEY.encode()).decrypt(token.encode()).decode() == second


# Rotation


def test_s2_13_rotate_re_encrypts_every_key_and_prints_counts_only(client, admin, project, dsn, monkeypatch):
    key = new_key()
    client.put(f"/projects/{project['slug']}/llm/providers/openai", json={"api_key": key}, headers=admin)
    client.put(f"/projects/{project['slug']}/llm/systems/card_agent",
               json={"provider": "openai", "model": "gpt-a"}, headers=admin)
    newest = Fernet.generate_key().decode()
    env = {**os.environ, "PLATFORM_DATABASE_URL": dsn, "PLATFORM_SECRETS_KEY": f"{newest},{SECRETS_KEY}",
           "PYTHONPATH": os.pathsep.join([str(PLATFORM_DIR), str(PLATFORM_DIR.parent / "shared/identity")])}
    done = subprocess.run([sys.executable, "-m", "platform_service.llm_store", "rotate"], cwd=PLATFORM_DIR,
                          env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    out = done.stdout + done.stderr
    assert re.search(r"\d", done.stdout), "rotate printed no counts"
    for secret in (key, newest, SECRETS_KEY):
        assert secret not in out
    token = one(dsn, project, "select ciphertext from llm.provider where provider = 'openai'")[0]
    assert Fernet(newest.encode()).decrypt(token.encode()).decode() == key

    monkeypatch.setenv("PLATFORM_SECRETS_KEY", newest)   # the old key removed
    r = client.get(f"/internal/projects/{project['pid']}/llm/card_agent",
                   headers={"X-AISC-Service-Token": INTERNAL_TOKEN})
    assert r.status_code == 200 and r.json()["api_key"] == key
