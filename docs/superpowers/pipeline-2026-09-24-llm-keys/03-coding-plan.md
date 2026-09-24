# 03 Coding plan: per-project LLM keys and model choice

Stage 3 of the pipeline in this folder. Read RULES.md, then 01-specs.md (the requirements) and
02-tests.md (the contract, especially section 5, T1 to T11). This plan tells stage 4 what to write,
in which order, and how to prove each step. The tests are the contract: do not edit them. Where
this plan and a test disagree, the test wins; tell the next stage in PROGRESS.md.

## 0. Ground rules for stage 4

- Branch `feat/unified-modules` everywhere (checked 2026-09-24: top-level, apps/qualification at
  226618c, apps/control-objectives at 97ad187). Local commits only, by explicit path. NEVER push.
- Never `docker compose up/down/build/restart`, never touch the live DBs or containers.
  `docker compose config` on copies (the compose test fixture) is allowed.
- `homepage/project.html` holds the user's uncommitted edit (card padding, `.card.split`, a shorter
  Qualify text). Task 12 edits on top of it and does NOT commit it.
- ALWAYS set `PLATFORM_TEST_DATABASE_URL` for any platform pytest run, even the no-DB catalogue
  file: `platform/tests/conftest.py` has a session-scoped autouse fixture that, when no test URL is
  set, connects to the LIVE database (`127.0.0.1:5432`) and deletes `pytest-*` projects there.
- TDD: the tests exist and are red. Write code until the task's tests are green, then run the
  task's "no regressions" command, then commit.
- No em dashes in any prose you write (docs, comments, commit messages).

### 0.1 One throwaway Postgres for the whole stage

Start it once, before Task 2 (the platform conftest needs it even for the no-DB file), and remove it at the end (Task 13). Never port 5432.

```
cd /home/listuser/aisc-install
NAME=aisc-t-llmkeys-$(openssl rand -hex 4); PW=$(openssl rand -hex 12)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
[ "$PORT" != 5432 ] || exit 1
docker run --rm -d --name $NAME -p 127.0.0.1:$PORT:5432 -e POSTGRES_USER=aisc-postgres-user \
  -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=platform postgres:14-alpine
until docker exec $NAME pg_isready -U aisc-postgres-user -d platform; do sleep 1; done; sleep 2
for f in platform-db project-databases inspector-role report-roles; do
  docker exec -i $NAME psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 -q < init/$f.sql; done
echo "NAME=$NAME PORT=$PORT PW=$PW" > /tmp/claude-llmkeys-db.env   # or your scratchpad; never commit
```

Shell state does not persist between tool calls: re-read NAME/PORT/PW from that file each time.
Shorthands used below:

```
PT="PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform PLATFORM_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform"
BT="CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test"
A=/home/listuser/aisc-install/apps/qualification/services/agents
```

A's suite always runs from a scratch directory (root-owned `application.log` in `$A`, see 02-tests
section 3): `cd <scratchpad> && uv run --no-project --with-requirements $A/requirements.txt --with
pytest --with httpx --with rdflib python -m pytest -q -p no:cacheprovider -c $A/pytest.ini
--rootdir $A <paths>`. Written below as `ARUN <paths>`.

## 1. Task order at a glance

| # | repo | what | turns green |
|---|---|---|---|
| 1 | top-level | platform runtime deps httpx + cryptography, uv.lock | KEYS s6_5 (2) |
| 2 | top-level | `platform_service/llm_catalogue.py` | CAT (all) |
| 3 | top-level | `project-template/0005_llm.sql` + `platform_service/llm_store.py` | STORE schema tests |
| 4 | top-level | llm routes + internal resolve route + validation handler in `app.py` | API (all), STORE (rest) |
| 5 | apps/qualification | `fill/baf_llm.py`, `fill/llm.py` as a thin wrapper | ABL, test_llm.py |
| 6 | apps/qualification | `service.py` `?project=`, `agent.fill_one(project=)` | APL, test_service.py |
| 7 | apps/control-objectives | `baf_llm.py` (byte copy), `llm.py` as a thin wrapper | BBL, test_llm.py |
| 8 | apps/control-objectives | `Projects(mapper_for=)`, 502 routes, `server.build_app` wiring | BPL, whole B suite |
| 9 | apps/qualification | FillerClient `projectId`, createFromForm `{id, projectId}`, action | FT, CV S3.8, tsc |
| 10 | top-level | compose, secrets.sh, Caddyfile, env comments, verify script | COMPOSE s6_*, KEYS s6_3/s6_4/s6_6 |
| 11 | top-level | `homepage/llm.html` | KEYS s4_1, s4_3 to s4_8 |
| 12 | top-level (NOT committed) | Manage link in `homepage/project.html` | KEYS s4_2 |
| 13 | top-level | parity check, submodule pointer bump, full suites, cleanup | KEYS s3_1 (3), everything |

## 2. Tasks

### Task 1. Platform runtime dependencies (S6.5)

Tests: `scripts/tests/test_llm_keys.py::test_s6_5_the_platform_depends_on_httpx_and_cryptography_at_runtime`
(red), `::test_s6_5_the_agents_need_nothing_new` (guard, stays green).

Files (top-level):
- `platform/pyproject.toml`: add to `[project] dependencies` the exact strings `"httpx>=0.27"` and
  `"cryptography>=43"` (the test compares strings). Keep `httpx>=0.27` in the `dev` extra too, or
  drop it there; either is fine.
- `platform/uv.lock`: from `platform/`, run `uv lock` (read-only network to PyPI is fine; both
  packages are already in the lock, so `uv lock --offline` also works if the network is not
  available). Check `aisc-platform`'s `dependencies` now name `httpx` and `cryptography`.
- Nothing in `platform/Dockerfile` (it installs from pyproject). Nothing in A's requirements.txt or
  B's pyproject.

Run: from the repo root, `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider
scripts/tests/test_llm_keys.py -k s6_5` (2 passed).

Commit (top-level): `git add platform/pyproject.toml platform/uv.lock && git commit -m "LLM keys,
stage 4: the platform depends on httpx and cryptography at runtime"`.

### Task 2. The provider catalogue and live model listers (S2.3, S2.15 to S2.19, S5.3, S5.6, S5.8)

Tests: all of `platform/tests/test_llm_catalogue.py` (no DB, fake HTTP).

New file (top-level): `platform/platform_service/llm_catalogue.py`. No DB, no FastAPI, no import of
other platform modules. Only `httpx`, `json`, `logging`, `os`, `dataclasses`.

Module contents:

```python
@dataclass(frozen=True)
class Provider:
    label: str
    key_required: bool
    base_url_editable: bool
    lister: str        # "openai" | "mistral" | "anthropic" | "google" | "together" | "ollama" | "compatible"

PROVIDERS: dict[str, Provider]   # exactly the 13 ids, alphabetical, e.g.
#   "anthropic": Provider("Anthropic", True, False, "anthropic")
#   "compatible": Provider("OpenAI-compatible endpoint", False, True, "compatible")
#   "deepseek": Provider("DeepSeek", True, False, "openai")
#   "google": Provider("Google Gemini", True, False, "google")
#   "groq": Provider("Groq", True, False, "openai")
#   "meta": Provider("Meta Llama", True, False, "openai")
#   "mistral": Provider("Mistral AI", True, False, "mistral")
#   "ollama": Provider("Ollama", False, True, "ollama")
#   "openai": Provider("OpenAI", True, False, "openai")
#   "openrouter": Provider("OpenRouter", True, False, "openai")
#   "qwen": Provider("Qwen (Alibaba Cloud)", True, False, "openai")
#   "together": Provider("Together AI", True, False, "together")
#   "xai": Provider("xAI", True, False, "openai")

MODELS_URL: dict[str, str]   # the 11 hosted URLs of S2.19 EXACTLY as in the test's REAL_URLS,
                             # no query strings; no env read anywhere in this module at import
ANTHROPIC_VERSION = "2023-06-01"
MAX_PAGES = 10
MAX_BYTES = 5 * 1024 * 1024
MAX_IDS = 5000
MAX_ID_LEN = 200
CONNECT_TIMEOUT = 5.0
DEFAULT_TIMEOUT = 10.0

def list_timeout() -> float        # env PLATFORM_LLM_LIST_TIMEOUT read at call time; bad/<=0 -> 10.0
def list_models(provider: str, api_key: str | None = None, base_url: str | None = None) -> dict
    # -> {"models": list[str], "error": str | None}; never raises for provider trouble
```

Implementation notes (each is pinned by a test):
- Read `MODELS_URL[provider]` and `list_timeout()` inside `list_models` on every call (T2, T3):
  tests `monkeypatch.setitem(cat.MODELS_URL, ...)`, and one test does `importlib.reload(cat)`, so the
  module must be reload-safe (no side effects) and other modules must use
  `llm_catalogue.PROVIDERS` / `llm_catalogue.MODELS_URL` by attribute, never `from ... import
  MODELS_URL`, and never `isinstance(x, llm_catalogue.Provider)`.
- Unknown provider: raise `KeyError`/`ValueError` (the API checks first; not tested here).
- A hosted provider ignores `base_url` entirely (S5.6). `ollama` and `compatible` without a base URL
  answer `{"models": [], "error": f"{label} has no base URL"}`.
- One `httpx.Client(follow_redirects=False, timeout=httpx.Timeout(t, connect=min(CONNECT_TIMEOUT, t)),
  trust_env=False)` per call. `trust_env=False` so a proxy variable on the host can never carry the
  key elsewhere (and the tests' 127.0.0.1 servers are reached directly).
- Each page: `with client.stream("GET", url, params=..., headers=...) as r:`
  1. `r.status_code in (401, 403)` -> error `f"{label} refused the key (HTTP {code})"`.
  2. any other status outside 200..299 (3xx included, T4) -> `f"{label} answered HTTP {code}"`.
     Do not read or log the body.
  3. read with `r.iter_bytes()`, accumulating; the moment the total exceeds `MAX_BYTES`, stop and
     answer `f"{label} did not send a model list"` (also when `Content-Length` says so up front).
  4. `json.loads`; any decode error or unexpected shape -> `f"{label} did not send a model list"`.
- Exceptions: `httpx.TimeoutException` -> `f"{label} did not answer within {n} s"` where `n` prints
  as `1` for 1.0 (`int(t) if float(t).is_integer() else t`); any other `httpx.HTTPError` or `OSError`
  -> `f"could not reach {label}"`. Check the timeout class first (it subclasses TransportError).
- Never put the key, the URL's body or the exception text in a message or a log record. Log at most
  `logger.info("listing models for %s failed: %s", provider, <kind word>)`.
- Requests per lister:
  - `openai` kind (openai, deepseek, groq, meta, openrouter, qwen, xai): `GET MODELS_URL[p]`,
    `Authorization: Bearer K`; body must be a dict whose `data` is a list; ids from items that are
    dicts with `id`.
  - `mistral`: same as openai, then keep an item only if `capabilities` is absent, or is a dict whose
    `completion_chat` is truthy.
  - `anthropic`: headers `x-api-key: K`, `anthropic-version: 2023-06-01`, NO Authorization; params
    `{"limit": "1000"}` then `{"limit": "1000", "after_id": last_id}` while `has_more is True` and
    `last_id` is a non-empty str, at most `MAX_PAGES` requests. When the page cap is hit, answer the
    ids collected so far with `error: None`.
  - `google`: header `x-goog-api-key: K` (never a `key` query parameter); params
    `{"pageSize": "1000"}` then add `pageToken=<nextPageToken>` while it is a non-empty str, at most
    10 pages; body dict with `models` list; keep items whose `supportedGenerationMethods` is a list
    containing `"generateContent"`; id = `name` with a leading `models/` removed.
  - `together`: body is a top-level list (also accept a dict with a `data` list); keep items whose
    `type` is absent or in `{"chat", "language"}`.
  - `ollama`: URL = `base_url.rstrip("/")`, then drop one trailing `/v1`, then `+ "/api/tags"`; no
    auth header even if a key is given; body dict with `models` list; ids from `name`.
  - `compatible`: URL = `base_url.rstrip("/") + "/models"`; `Authorization: Bearer K` only when a key
    is given; body a dict with `data` list or a top-level list; ids from `id`.
- Id cleaning (S2.17): keep only `str` of length 1..200 (no strip), dedupe, sort, keep the first 5000.
  A shape error is "did not send a model list"; an empty but well-shaped list is success with `[]`.

Run: from `platform/`: `env $PT uv run --extra dev pytest -q -p no:cacheprovider
tests/test_llm_catalogue.py` (the throwaway DB must be up for the conftest's cleanup, see 0; start
it now if not yet). No regressions: the full platform command (section 3).

Commit (top-level): `git add platform/platform_service/llm_catalogue.py && git commit -m "LLM keys,
stage 4: the platform's provider catalogue and its live model listers"`.

### Task 3. Storage: the template file and llm_store (S1.1 to S1.6, S2.11, S2.13, S5.2)

Tests turned green by this task alone (they need no llm route): in `platform/tests/test_llm_store.py`
`test_s1_4_*` (2), `test_s1_1_*`, `test_s1_2_*` (7), `test_s1_3_*` (2), `test_s1_5_a_new_project_*`,
`test_s1_5_a_project_made_before_0005_*`, `test_s1_6_module_roles_cannot_read_the_llm_tables[*]` (3,
or skipped per missing role). The rest of STORE turns green in Task 4.

New file (top-level): `platform/project-template/0005_llm.sql`:

```sql
-- The per-project LLM keys and model choices (docs/superpowers/pipeline-2026-09-24-llm-keys).
-- Only the platform (the database owner) reads or writes them; no module role gets USAGE.
CREATE SCHEMA IF NOT EXISTS llm;
REVOKE ALL ON SCHEMA llm FROM PUBLIC;
CREATE TABLE IF NOT EXISTS llm.provider (
    provider   text PRIMARY KEY CHECK (provider ~ '^[a-z]{2,20}$'),
    ciphertext text NULL,
    base_url   text NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NULL
);
CREATE TABLE IF NOT EXISTS llm.system_choice (
    system     text PRIMARY KEY CHECK (system IN ('card_agent', 'risk_mapper')),
    provider   text NOT NULL REFERENCES llm.provider (provider) ON DELETE RESTRICT,
    model      text NOT NULL CHECK (length(model) BETWEEN 1 AND 200),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NULL
);
REVOKE ALL ON ALL TABLES IN SCHEMA llm FROM PUBLIC;
```

Traps: the S1.4 test regex flags any `CREATE SCHEMA|TABLE|INDEX` not followed by `IF NOT EXISTS`,
comments included, so never write those words in a comment. No `BEGIN;`/`COMMIT;` lines (the file
runs inside `migrate()`'s transaction). No `DO` block is needed. Nothing else changes: `provision`
and `provision_all` already apply new template files (S1.5).

New file (top-level): `platform/platform_service/llm_store.py`. Imports: `os`, `sys`, `hmac` only if
you put the token check here (see Task 4), `psycopg`, `psycopg.rows.dict_row`,
`psycopg.conninfo.make_conninfo`, `cryptography.fernet (Fernet, MultiFernet, InvalidToken)`,
`platform_service.projectdb`, `platform_service.db` (for `dsn()` only). It must not import `app`.

```python
SYSTEMS: dict[str, str] = {"card_agent": "Card agent (Qualification)",
                           "risk_mapper": "Risk mapper (Control objectives)"}   # order matters (S2.4)
DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
KEEP = object()                      # sentinel: "leave this column as it is"

class SecretsKeyError(RuntimeError): ...   # str() is the 503 detail
class KeyUnreadable(RuntimeError): ...     # str() = f"the stored key for {provider} cannot be decrypted; enter it again"

def ollama_default() -> str          # env PLATFORM_OLLAMA_BASE_URL (read per call, T5) or the default
def fernet() -> MultiFernet          # env PLATFORM_SECRETS_KEY read per call (T5):
    # unset or blank after strip -> SecretsKeyError("PLATFORM_SECRETS_KEY is not set")
    # split on ",", strip, drop empties; any member Fernet() rejects (ValueError/TypeError)
    #   -> SecretsKeyError("PLATFORM_SECRETS_KEY is not a list of Fernet keys")   (T7)
def encrypt(plaintext: str) -> str   # fernet().encrypt(...).decode()
def decrypt(provider: str, token: str) -> str   # InvalidToken -> KeyUnreadable(provider)

def connect(pid) -> psycopg.Connection
    # psycopg.connect(make_conninfo(db.dsn(), dbname=projectdb.database_name(pid)), row_factory=dict_row)
def providers(pid) -> dict[str, dict]
    # select provider, ciphertext is not null as has_key, base_url, updated_at from llm.provider
    # NEVER select ciphertext itself into anything that reaches a response
def ciphertext_of(pid, provider) -> str | None     # the one place ciphertext is read
def save_provider(pid, provider, *, ciphertext=KEEP, base_url=KEEP, subject: str | None) -> dict
    # INSERT ... ON CONFLICT (provider) DO UPDATE SET
    #   ciphertext = CASE WHEN %(set_key)s THEN EXCLUDED.ciphertext ELSE llm.provider.ciphertext END,
    #   base_url   = CASE WHEN %(set_url)s THEN EXCLUDED.base_url   ELSE llm.provider.base_url   END,
    #   updated_at = now(), updated_by = EXCLUDED.updated_by
    # RETURNING provider, ciphertext IS NOT NULL AS has_key, base_url, updated_at
def delete_provider(pid, provider) -> list[str] | bool
    # one transaction: systems = select system from llm.system_choice where provider=%s order by system
    # systems -> return the list (caller answers 409, nothing deleted)
    # else delete ... returning provider -> True if a row went, False if none (404)
def choices(pid) -> dict[str, dict]            # system -> {"provider", "model"}
def save_choice(pid, system, provider, model, *, subject, keyless_row: bool) -> None
    # one transaction: when keyless_row, insert into llm.provider (provider) values (%s)
    # on conflict do nothing; then upsert llm.system_choice
def delete_choice(pid, system) -> bool
def resolve_choice(pid, system) -> dict | None
    # join system_choice and provider: {"provider","model","ciphertext","base_url"} or None
def rotate_all(base_dsn: str) -> dict[str, int]
def main(argv: list[str]) -> int
if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
```

Rotation (S2.13, T8, G3): `main(["rotate"])` builds `fernet()` first (a `SecretsKeyError` prints its
message to stderr and returns 2), then `rotate_all(db.dsn())`: read pids with a plain
`psycopg.connect(base_dsn)` and `select pid from core.project order by created_at` (do NOT call
`db.pool()`: it would migrate, provision and register dashboards); for each project connect to its
database; a connection error counts as `unreachable` and continues; `to_regclass('llm.provider')` null
counts as `without_llm` and continues; for every row with `ciphertext is not null`,
`MultiFernet.rotate(token)`, update it, count `rotated`; `InvalidToken` counts `unreadable` and
continues (never aborts, never exits non-zero for it). Commit per project. Print one line, counts
only, e.g. `rotated 3 keys in 2 projects (0 unreadable, 0 without llm tables, 0 unreachable)`. Never
print a key, a token, the DSN or a Fernet key. Any other argv: print usage, return 2.

Run: `env $PT uv run --extra dev pytest -q -p no:cacheprovider tests/test_llm_store.py` from
`platform/`: the tests listed above pass; the ones that PUT a key still fail with 404 (Task 4).
No regressions: full platform command, pre-existing 110 passed, 2 skipped.

Commit (top-level): `git add platform/project-template/0005_llm.sql platform/platform_service/llm_store.py
&& git commit -m "LLM keys, stage 4: each project database keeps its LLM keys, Fernet-encrypted, with
a rotate command"`.

### Task 4. The platform routes (S2.1, S2.2, S2.4 to S2.14, S2.20 to S2.26, S5.1, S5.3, S5.4, S5.5, S5.7)

Tests: all of `platform/tests/test_api_llm.py`, and the rest of `test_llm_store.py`
(`test_s1_5_deleting_*`, `test_s1_6_the_inspector_*`, `test_s5_2_s2_11_*`,
`test_s2_11_the_newest_key_*`, `test_s2_13_rotate_*`).

File (top-level): `platform/platform_service/app.py` (routes stay in app.py as the spec says).
Imports to add: `hmac`, `unicodedata`, `urllib.parse.urlsplit`, `from fastapi import Request`,
`from fastapi.exceptions import RequestValidationError`, `from fastapi.encoders import
jsonable_encoder`, `from pydantic import ConfigDict, StrictStr`, `from platform_service import
llm_catalogue, llm_store`. Every route below is a plain `def` (sync psycopg and httpx).

4.1 Validation handler (S2.14), app-wide:

```python
@app.exception_handler(RequestValidationError)
def validation_without_values(_request, exc):
    detail = [{k: v for k, v in e.items() if k not in ("input", "ctx")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})
```

No pre-existing test reads `input`/`ctx` (checked). The non-JSON PUT (S5.7, `text/plain`) reaches
the model as bytes, fails `model_attributes_type` and comes back 422 without its input: nothing to do
beyond this handler.

4.2 Bodies:

```python
class ProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: StrictStr | None = None
    base_url: StrictStr | None = None

class SystemChoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: StrictStr
    model: StrictStr
```

4.3 Helpers in app.py:

```python
NOT_VALID_KEY = "the key is not a valid API key string"

def admin_project(slug: str, caller: Caller) -> dict:
    role_or_404(slug, caller)              # a stranger: 404 "no project ..."
    if not caller.has_role(ADMIN_ROLE):    # a member, even the owner: 403
        raise HTTPException(403, "only a platform admin manages models and keys")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)             # unknown project, even for an admin (T6)
    return found

def catalogue_entry(provider: str):        # 404 f"no provider {provider!r}" (T6)
def clean_key(value: str) -> str           # strip; 1..4096; no c.isspace() and no
                                           # unicodedata.category(c).startswith("C") inside;
                                           # else HTTPException(422, NOT_VALID_KEY)
def clean_base_url(value: str) -> str | None   # "" after strip -> None (clears)
    # <= 500 chars, no whitespace or control chars, no "?" or "#" anywhere,
    # urlsplit: scheme in {"http","https"}, hostname non-empty, no username/password
    # (and no "@" in netloc), .port readable (ValueError -> 422); else 422
    # "the base URL must be http(s)://host[:port][/path], without credentials, query or fragment"
    # store the stripped string exactly as given (the test compares it)
def clean_model(value: str) -> str         # strip; 1..200; no category C chars; else 422
def provider_view(pid_or_rows, provider_id) -> dict
    # {"id","label","key_required","has_key","base_url","base_url_editable","usable","updated_at"}
    # has_key: row exists and has_key; base_url: stored, else ollama_default() for ollama, else None
    # usable: key_required -> has_key; ollama -> True; compatible -> stored base_url is not None
    # updated_at: row["updated_at"].isoformat() or None
```

4.4 Page-facing routes (every one: `caller: Caller = Depends(caller_dependency)` first, which gives
S2.2's 401, then `project = admin_project(slug, caller)`, then `pid = project["pid"]`):

| route | behaviour |
|---|---|
| `GET /projects/{slug}/llm` | `{"providers": [provider_view(...) for every id of llm_catalogue.PROVIDERS], "systems": [{"id","label","choice"} for SYSTEMS in order]}`; `choice` = `{"provider","model"}` or `None`. Never needs PLATFORM_SECRETS_KEY (S2.11). |
| `PUT /projects/{slug}/llm/providers/{provider}` body `ProviderIn` | 404 unknown provider; `set_fields = {k for k in body.model_fields_set if getattr(body, k) is not None}`, empty -> 422 "send api_key, base_url or both"; `base_url` for a provider that is not `base_url_editable` -> 422; `api_key` for `ollama` -> 422 "ollama takes no key" (decision); validate everything BEFORE any encryption or write; then `ciphertext = llm_store.encrypt(clean_key(...))` (SecretsKeyError -> 503 with its message); `llm_store.save_provider(..., subject=caller.subject)`; answer 200 `provider_view`. |
| `DELETE /projects/{slug}/llm/providers/{provider}` | 404 unknown provider; `llm_store.delete_provider`: list -> 409 `f"{provider} is used by {', '.join(systems)}; choose another provider for it first"`; False -> 404 `f"nothing is stored for {provider}"`; True -> `Response(status_code=204)`. |
| `GET /projects/{slug}/llm/providers/{provider}/models` | 404 unknown; not usable -> 409 (`f"{label} has no key in this project"` or `"... no base URL ..."`); key: `ciphertext_of` then `llm_store.decrypt` (KeyUnreadable -> 200 `{"models": [], "error": str(exc)}`; SecretsKeyError -> 503, decision); base_url: stored or `ollama_default()` for ollama, stored for compatible, None for hosted; answer `llm_catalogue.list_models(provider, api_key=key, base_url=base_url)` with 200. |
| `PUT /projects/{slug}/llm/systems/{system}` body `SystemChoiceIn` | 404 `f"no system {system!r}"` when not in SYSTEMS; 422 unknown provider (not 404, the test wants 422); 422 not usable (same rule as `provider_view`); `model = clean_model(...)`; `save_choice(..., keyless_row=(provider == "ollama"))`; 200 `{"system","provider","model"}`. No provider call (D6). |
| `DELETE /projects/{slug}/llm/systems/{system}` | 404 unknown system; `delete_choice` False -> 404 `f"{system} has no choice to remove"`; else 204. |

4.5 The internal resolve route `GET /internal/projects/{pid}/llm/{system}`, `pid: str` (not
`uuid.UUID`, so the order below holds), `request: Request`, no caller dependency. Every answer,
errors included, is a `JSONResponse` with header `Cache-Control: no-store` (S2.26), in this order:
1. `x-forwarded-for` or `x-forwarded-host` present -> 404 `{"detail": "not here"}` (S2.24).
2. `expected = os.environ.get("PLATFORM_INTERNAL_TOKEN", "")` read per request; empty -> 503
   `"the internal route is closed: PLATFORM_INTERNAL_TOKEN is not set"` (S2.23).
3. `given = request.headers.get("x-aisc-service-token", "")`;
   `hmac.compare_digest(given.encode(), expected.encode())` false -> 401 `"a service token is
   needed"`. (The S2.23 source test greps `compare_digest` and `PLATFORM_INTERNAL_TOKEN` in app.py.)
4. `not looks_like_pid(pid)` -> 422 `"not a project id"`.
5. system not in SYSTEMS -> 404 `f"no system {system!r}"`.
6. `db.get_project(pid)` None -> 404 `f"no project {pid!r}"`.
7. `choice = llm_store.resolve_choice(pid, system)`; None -> 200 `{"configured": False}`.
8. provider = choice's; `base_url` = stored, or `ollama_default()` for ollama; `compatible` without
   a stored base URL -> 409 `"no base URL is stored for compatible"`.
9. `api_key`: ollama -> None; ciphertext None -> key_required -> 409 `f"no key is stored for
   {provider} in this project"` (G4), compatible -> None; else `llm_store.decrypt` (SecretsKeyError
   -> 503 with its message, S2.11; KeyUnreadable -> 409 with its message, S2.12).
10. 200 `{"configured": True, "provider", "model", "base_url", "api_key"}`.

Security notes: no route but step 10 ever carries a key; no response carries `ciphertext`
(`providers()` does not even select it); never log a request body, a key or a token; do not add CORS
middleware (S5.7 guard). `role_or_404`'s 404 happens before 403 for every llm route, so strangers
learn nothing.

Run: from `platform/`: `env $PT uv run --extra dev pytest -q -p no:cacheprovider tests/test_api_llm.py
tests/test_llm_store.py tests/test_llm_catalogue.py`, then the full platform command. Expected: every
llm test passes (a `report_ro` / `inspector_ro` case may skip if the role cannot log in), pre-existing
110 still pass.

Commit (top-level): `git add platform/platform_service/app.py && git commit -m "LLM keys, stage 4:
admin-only routes for keys, live models and choices, and the internal resolve route"`.

### Task 5. The shared module in A: `fill/baf_llm.py` (S3.1 to S3.6, S3.11, S5.3)

Tests: `$A/tests/test_baf_llm.py` (all), `$A/tests/test_llm.py` (19, unchanged, S3.6).

New file (apps/qualification): `services/agents/fill/baf_llm.py`. It will be copied byte for byte to
B in Task 7, so: imports only stdlib, `baf` and `__future__`, absolute only (no `from .`), no mention
of either package's name or path in code or docstring. Move the 13-entry `PROVIDERS` table (with the
13 BAF wrapper imports and the comments) and `OPTIONAL_KEY` here unchanged (tuple of 3:
wrapper, key property, env var).

```python
DEFAULT_PROVIDER = "mistral"
DEFAULT_MODEL = "mistral-large-latest"
SYSTEMS = ("card_agent", "risk_mapper")
SYSTEM_LABELS = {"card_agent": "card agent", "risk_mapper": "risk mapper"}   # for messages
Completer = Callable[..., str]          # from collections.abc

@dataclass(frozen=True, repr=False)
class LlmConfig:
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    def __repr__(self): ...   # "LlmConfig(provider='openai', model='gpt', api_key=<set>, base_url=None)"
                              # api_key shows "<set>" when truthy, "None" otherwise
    __str__ = __repr__

class ResolveError(RuntimeError): ...

def config_from_env(env: Mapping[str, str] | None = None, provider=None, model=None) -> LlmConfig
    # env None -> os.environ; provider = (provider or env BAF_LLM_PROVIDER or DEFAULT).lower();
    # model = model or env BAF_LLM_MODEL or DEFAULT; api_key = env[PROVIDERS[p][2]] or None
    # (None for an unknown provider or a keyless one); base_url = env BAF_LLM_BASE_URL or None
def resolve(project, system, env=None, timeout=None) -> LlmConfig | None
def config_for(project, system, env=None, fallback=None) -> LlmConfig
    # resolve(...) or fallback or config_from_env(env)   (a ResolveError propagates, D4)
def build_llm(config: LlmConfig, agent=None, agent_name: str = "llm")
def completer(llm) -> Completer          # unchanged body from today's llm.py
```

`resolve` (S3.4), stdlib only (`urllib.request`, `urllib.error`, `json`, `socket`):
- `env = os.environ if env is None else env`; `if not project: return None`;
  `base = (env.get("PLATFORM_URL") or "").rstrip("/")`, `token = env.get("PLATFORM_INTERNAL_TOKEN")
  or ""`; either empty -> `None`.
- `t = timeout if timeout is not None else float(env.get("LLM_RESOLVE_TIMEOUT") or 5)`.
- URL `f"{base}/internal/projects/{quote(str(project), safe='')}/llm/{quote(system, safe='')}"`,
  header `X-AISC-Service-Token: token`, `Accept: application/json`.
- Opener: `urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())` where
  `_NoRedirect.redirect_request` returns None: no proxy from the environment, no redirect (the token
  never travels elsewhere; a 3xx becomes an HTTPError and so a ResolveError).
- Message prefix: `f"the platform could not resolve the {label} model for project {project}"`.
  - `HTTPError e`: read at most 64 KB, `detail` = the JSON body's `detail` when it is a `str`, else
    `f"HTTP {e.code}"`; raise `ResolveError(f"{prefix}: {detail}")`.
  - `TimeoutError`/`socket.timeout`, or `URLError` whose reason is one: `f"{prefix}: the platform did
    not answer within {t} s"`; any other `URLError`/`OSError`: `f"{prefix}: the platform is not
    reachable"`. Never put the token or the URL's query in it (the project id is fine: tests want it).
  - 200: body not JSON, not a dict -> ResolveError `"...: the platform's answer is not a model
    choice"`; `configured is False` -> None; `configured is True` with `provider`/`model` non-empty
    str and `api_key`/`base_url` str or None -> `LlmConfig(...)`; anything else -> the same
    ResolveError. Do not validate `provider` against PROVIDERS here (APL's build-error test needs
    `telepathy` to reach `build_llm`).

`build_llm(config, agent=None, agent_name="llm")` (S3.3), same logic as today's but from the config:
- `provider = (config.provider or "").lower()`; unknown -> `ValueError(f"{provider!r} is not a
  provider this service configures; expected one of {', '.join(sorted(PROVIDERS))}")` (A's legacy
  test wants "mistral", B's wants "not a provider", APL wants the name).
- `agent = agent if agent is not None else Agent(agent_name)`: a fresh BAF Agent per build, so the
  property store (and its key) is never shared across projects.
- key = `config.api_key or None`; `if key and key_property is not None: agent.set_property(...)`;
  `elif provider not in OPTIONAL_KEY: raise ValueError(f"{provider} needs {env_var}: set it in the
  environment, or store a key for the project")` (must contain the env var name; must not contain
  the key: it cannot, since there is none).
- ollama with `config.base_url` -> `agent.set_property(nlp.OLLAMA_BASE_URL, base_url)`.
- compatible: no base URL -> `ValueError("compatible needs a base URL (BAF_LLM_BASE_URL, or one
  stored for the project): it is the provider for an endpoint you host, so there is no default to
  fall back on")` (ABL matches "base", B's legacy test matches "BAF_LLM_BASE_URL"); else
  `parameters = {"base_url": base_url, "api_key": key or "not-needed"}`.
- `llm = wrapper(agent=agent, name=config.model, parameters=parameters); llm.initialize()`.
- Never read or write `os.environ` in `build_llm`.
- R2 contingency: if `test_s5_3_building_and_predicting_log_no_key` shows the key in the log, find
  the logger that printed it and raise that logger's level inside `build_llm` / around `predict`
  (restore after); never patch BAF or the SDKs.

File (apps/qualification): `services/agents/fill/llm.py` becomes a thin wrapper that keeps today's
API (S3.6): keep its docstring (updated to say the table lives in baf_llm), and

```python
import os
from fill.baf_llm import (DEFAULT_MODEL, DEFAULT_PROVIDER, OPTIONAL_KEY, PROVIDERS, Completer,
                          LlmConfig, completer, config_from_env)
from fill import baf_llm

def build_llm(provider=None, model=None, agent=None):
    """A BAF LLM, configured from the environment (today's behaviour)."""
    return baf_llm.build_llm(config_from_env(os.environ, provider, model), agent=agent,
                             agent_name="ontology_filler_llm")
```

(`legacy.PROVIDERS` is then the same object as `baf_llm.PROVIDERS`, which S3.2's test accepts.)

Run: `ARUN $A/tests/test_baf_llm.py $A/tests/test_llm.py`, then `ARUN $A/tests` (APL still red until
Task 6; everything else green, including the 100 pre-existing).

Commit (apps/qualification): `git -C apps/qualification add services/agents/fill/baf_llm.py
services/agents/fill/llm.py && git -C apps/qualification commit -m "LLM keys, stage 4: one BAF
building module, fed by an env or a platform-resolved config"`.

### Task 6. The card agent works for a project (S3.7)

Tests: `$A/tests/test_project_llm.py` (8), `$A/tests/test_service.py` (8, unchanged, T9).

File (apps/qualification) `services/agents/service.py`:
- `from uuid import UUID`; `start(qualification_id: str, background: BackgroundTasks, project: UUID |
  None = None)`: FastAPI answers 422 for a non-UUID `?project=` before anything starts.
- `pid = str(project) if project is not None else None`; the new RUNS entry gets `"project": pid`;
  `background.add_task(_run, qualification_id, pid)`.
- `_run(qualification_id, project=None)`: `result = fill_one(qualification_id) if project is None
  else fill_one(qualification_id, project=project)`. The no-project call MUST keep the one-argument
  form: test_service.py's fakes take only `qualification_id` (T9). Keep calling the module-global
  `fill_one` (tests monkeypatch `service.fill_one`). The failure branch stays `str(exc)`.

File (apps/qualification) `services/agents/agent.py`:
- `from fill import baf_llm` (keep `from fill import clients` and `from fill.workflow import
  MAX_ROUNDS, build_agent, run_fill`; the tests monkeypatch `agent.run_fill` and `agent.clients.*`,
  so keep calling them through those module globals).
- `def fill_one(qualification_id: str, dry_run: bool = False, project: str | None = None) -> dict:`
  first `config = baf_llm.config_for(project, "card_agent")`, then `llm = baf_llm.build_llm(config,
  agent_name="ontology_filler_llm")` (both before fetching the qualification: a ResolveError or
  ValueError fails the run fast, and its message has no key), then as today with
  `complete=baf_llm.completer(llm)`; the returned dict gains `"model":
  f"{config.provider}/{config.model}"`.
- `main()`: add `--project` (optional) and pass it through; `--serve` stays env-configured (out of
  scope). Update the module docstring's first paragraph.
- `fill/llm.py` import in agent.py is no longer needed; remove it.

Run: `ARUN $A/tests` (all green: 146 passed, 100 pre-existing + 46 new, 0 failed).

Commit (apps/qualification): `git -C apps/qualification add services/agents/service.py
services/agents/agent.py && git -C apps/qualification commit -m "LLM keys, stage 4: the card agent
takes ?project= and uses that project's model"`.

### Task 7. The same module in B (S3.1, S3.2 to S3.6, S3.11)

Tests: `apps/control-objectives/tests/test_baf_llm.py` (all, same names as ABL),
`tests/test_llm.py`, `tests/test_config.py`, `tests/test_server.py` (unchanged).

Files (apps/control-objectives):
- `src/aisc_control_objectives/baf_llm.py`: `cp apps/qualification/services/agents/fill/baf_llm.py
  apps/control-objectives/src/aisc_control_objectives/baf_llm.py`, then `cmp` the two. Never edit
  one without the other.
- `src/aisc_control_objectives/llm.py`: delete its own `PROVIDERS`, `OPTIONAL_KEY`, `DEFAULT_*`,
  `Completer`, `completer`, the 13 wrapper imports and the `nlp`/`Agent` imports; import them from
  `aisc_control_objectives.baf_llm` (re-exported names: `PROVIDERS, OPTIONAL_KEY, DEFAULT_PROVIDER,
  DEFAULT_MODEL, Completer, completer`). Keep `json_object`, `_try_json`, `parse_into`, `T` and the
  pydantic import unchanged. `build_llm(provider, model, agent=None)` becomes
  `baf_llm.build_llm(baf_llm.config_from_env(os.environ, provider, model), agent=agent,
  agent_name="control_objectives_llm")`. `config.py` and `risk_mapping.py` keep importing from
  `llm` and need no change.

Run: from `apps/control-objectives`: `env $BT uv run --extra dev pytest -q -p no:cacheprovider
tests/test_baf_llm.py tests/test_llm.py tests/test_config.py tests/test_server.py`, then the full B
command (only BPL may still be red).

Commit (apps/control-objectives): `git -C apps/control-objectives add
src/aisc_control_objectives/baf_llm.py src/aisc_control_objectives/llm.py && git -C
apps/control-objectives commit -m "LLM keys, stage 4: the shared BAF building module, byte-identical
to the card agent's"`.

### Task 8. The risk mapper works with its project's model (S3.9, S3.10, D8)

Tests: `apps/control-objectives/tests/test_project_llm.py` (all), then the whole B suite.

File `src/aisc_control_objectives/projects.py`:
- `from collections.abc import Callable`; `from aisc_control_objectives.baf_llm import ResolveError`;
  `MapperFor = Callable[[str], tuple[Mapper, str]]`.
- `class ModelUnavailable(RuntimeError): """The project's model could not be had; nothing was saved."""`
- `Projects.__init__(..., model: str = "", mapper_for: MapperFor | None = None)` (keyword, T10);
  store it.
- `map_risks_of`: after `record = self._repository.get(project_id)`, `mapper, model = self._mapper,
  self._model`; when `self._mapper_for` is set: `try: mapper, model = self._mapper_for(record.project)
  except (ResolveError, ValueError) as exc: raise ModelUnavailable(str(exc)) from exc`; then
  `map_risks(record.ontology.risks, mapper, self._catalogue)` and `save_mapping_run(..., model=model)`.
  The message stays exactly `str(exc)` (the test compares `{"detail": message}`).

File `src/aisc_control_objectives/api/app.py`:
- import `ModelUnavailable` from `projects`.
- `POST /api/projects/{project_id}/map`: `try: return payload(projects.map_risks_of(project_id))
  except ModelUnavailable as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc`.
- `POST /p/{project}/projects/{project_id}/map` (map_form): `try: projects.map_risks_of(project_id)
  except ModelUnavailable as exc: return PlainTextResponse(str(exc), status_code=502)`.

File `src/aisc_control_objectives/server.py` `build_app()`:
- keep `complete = _build_completer(config)` at startup and the fixed `RiskMapper` (D8, test_server.py
  unchanged).
- add, after `objectives` is loaded:

```python
from aisc_control_objectives import baf_llm
startup = baf_llm.config_from_env(os.environ, config.provider, config.model)

def mapper_for(pid: str):
    chosen = baf_llm.config_for(pid, "risk_mapper", fallback=startup)
    llm = baf_llm.build_llm(chosen, agent_name="control_objectives_llm")
    return (RiskMapper(complete=baf_llm.completer(llm), catalogue=objectives),
            f"{chosen.provider}/{chosen.model}")
```

  and pass `mapper_for=mapper_for` to `Projects(...)` (keywords, as today; the test captures kwargs).
  Resolve per map call, no cache (D10). Update the env list in the module docstring
  (`PLATFORM_INTERNAL_TOKEN`, `LLM_RESOLVE_TIMEOUT`).

Run: from `apps/control-objectives`: `env $BT uv run --extra dev pytest -q -p no:cacheprovider`
(expected 297 passed, 250 pre-existing + 47 new, 1 skipped, 0 failed).

Commit (apps/control-objectives): `git -C apps/control-objectives add
src/aisc_control_objectives/projects.py src/aisc_control_objectives/api/app.py
src/aisc_control_objectives/server.py && git -C apps/control-objectives commit -m "LLM keys, stage
4: each map uses the model its project chose, and a model it cannot have is a 502"`.

### Task 9. qualification-web passes the project id (S3.8)

Tests: `test/unit/FillerTrigger.test.ts` (S3.8 block, 4) and `test/unit/cardVersionsInCoreSystem.test.ts`
(S3.8 block, 2), plus `npx tsc --noEmit`.

Files (apps/qualification):
- `src/server/services/FillerClient.ts`: `async request(qualificationId: string, projectId?: string)`;
  URL `${this.serviceUrl}/fill/${qualificationId}` plus `?project=${encodeURIComponent(projectId)}`
  only when `projectId` is given (non-empty); everything else unchanged (never throws, `res.ok`, no
  call without a URL). `export async function requestFill(qualificationId: string, projectId?: string)`
  passes it through (build the client inside the function, as today, so a stubbed global `fetch` is
  used).
- `src/server/services/QualificationService.ts`: `createFromForm(...): Promise<{ id: string;
  projectId: string }>`: `const made = await this.repo.create({...}); return { id: made.id,
  projectId: version.project_id };` (exactly these two keys: the test uses `toEqual`).
- `src/app/p/[project]/qualify/new/actions.ts`: `let made: { id: string; projectId: string };`
  `made = await qualificationService.createFromForm(project, formData)` in the try;
  `await requestFill(made.id, made.projectId)`; `redirect(`/p/${project}/qualify/${made.id}`)`.
  Update the comment above the call ("... for this project, so it uses the project's model").

Run: from `apps/qualification`: `npx vitest run test/unit/FillerTrigger.test.ts
test/unit/cardVersionsInCoreSystem.test.ts && npx tsc --noEmit`; then `npx vitest run` (whole
suite, no regressions; `cardSubmission.test.ts` destructures `{ id }` and keeps working).

Commit (apps/qualification): `git -C apps/qualification add src/server/services/FillerClient.ts
src/server/services/QualificationService.ts "src/app/p/[project]/qualify/new/actions.ts" && git -C
apps/qualification commit -m "LLM keys, stage 4: the save tells the card agent its project"`.

### Task 10. Compose, secrets, proxy and env wiring (S6.1 to S6.4, S6.6, S6.7, S5.5)

Tests: `scripts/tests/test_compose.py::test_s6_1_*, test_s6_2_* (2), test_s6_7_*` and the 4
pre-existing; `scripts/tests/test_llm_keys.py::test_s6_3_* (2), test_s6_4_*, test_s6_6_* (2)`.
NOTHING here is applied to the running stack.

Files (top-level):
- `docker-compose.development.yml`:
  - service `platform`, `environment`: add
    `PLATFORM_SECRETS_KEY: ${PLATFORM_SECRETS_KEY:?run scripts/secrets.sh first}`,
    `PLATFORM_INTERNAL_TOKEN: ${PLATFORM_INTERNAL_TOKEN:?run scripts/secrets.sh first}`,
    `PLATFORM_OLLAMA_BASE_URL: ${PLATFORM_OLLAMA_BASE_URL:-http://host.docker.internal:11434}`,
    with a short comment (keys encrypted at rest; the token guards the internal resolve route). It
    already has `host-gateway`; do NOT add `ports:`.
  - service `qualification-agents`, `environment`: add `PLATFORM_URL: http://platform:8000` and
    `PLATFORM_INTERNAL_TOKEN: ${PLATFORM_INTERNAL_TOKEN:?run scripts/secrets.sh first}`; add
    `extra_hosts: ["host.docker.internal:host-gateway"]` (same list style as the others).
  - service `control-objectives`, `environment`: add `PLATFORM_INTERNAL_TOKEN:
    ${PLATFORM_INTERNAL_TOKEN:?run scripts/secrets.sh first}` next to `PLATFORM_URL`.
  - No network changes. Do not set PLATFORM_OLLAMA_BASE_URL in `env.development` (the test expects
    the compose default).
- `scripts/secrets.sh`:
  - add `fernet() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }` next to `cookie()`, with a
    comment (Fernet wants urlsafe base64 of 32 bytes, WITH its `=` padding, 44 characters).
  - new-install heredoc: add `PLATFORM_INTERNAL_TOKEN=$(rand)` and `PLATFORM_SECRETS_KEY=$(fernet)`;
    change the echo to "13 secrets".
  - the append loop: handle both new names, each with its own generator, only when missing, e.g.
    loop the old four with `rand`, then
    `grep -q '^PLATFORM_INTERNAL_TOKEN=' "$OUT" || { echo "PLATFORM_INTERNAL_TOKEN=$(rand)" >> "$OUT"; echo "added ..."; }`
    and the same for `PLATFORM_SECRETS_KEY` with `$(fernet)`. Never replace an existing value.
  - `--rotate` (P9): a fresh PLATFORM_SECRETS_KEY would make every stored key unreadable, so
    `--rotate` carries the existing `PLATFORM_SECRETS_KEY` value over unchanged (read it with
    `awk -F= '/^PLATFORM_SECRETS_KEY=/{print substr($0, index($0,"=")+1)}'` before the heredoc and
    use it instead of `$(fernet)` when non-empty). Say in the header comment that this key is rotated
    by prepending a new key, running `python -m platform_service.llm_store rotate`, then dropping the
    old one (S2.13).
  - Test it ONLY through the test (scratch copy). Running it in the repo rewrites `env.runtime`.
- `Caddyfile`, launcher site `{$CADDY_DOMAIN}:{$HOMEPAGE_PORT}`: inside `route {`, before
  `handle_path /api/* {`, add

  ```
      # The platform's internal route (service token, resolved keys) is never served here.
      handle /api/internal/* {
        respond 404
      }
  ```

  Do not mention the literal `handle_path /api/*` in any comment above the block (the test uses the
  first occurrence).
- `env.development` and `env.staging`: two comment lines each, near the INTERNAL_API_KEY one:
  `# PLATFORM_SECRETS_KEY comes from env.secrets, written by scripts/secrets.sh and never committed`
  and the same for `PLATFORM_INTERNAL_TOKEN`. No `NAME=` lines.
- New `scripts/verify-llm-keys.sh` (01-specs section 8, last row; not run by the pipeline): read-only
  curl checks the user runs after a deployment: `curl -s -o /dev/null -w '%{http_code}'
  http://localhost:8100/api/internal/projects/00000000-0000-0000-0000-000000000000/llm/card_agent`
  must be 404; with a non-admin session cookie given in env `AISC_COOKIE` (never echoed),
  `/api/projects/<slug>/llm` must be 403. `set -euo pipefail`, prints PASS/FAIL per check, exit 1 on
  any FAIL. `chmod +x`.

Out of scope, recorded: `docker-compose.staging.yml` gets nothing (the spec wires development only);
note it as an open item.

Run: from the repo root: `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider
scripts/tests/test_compose.py scripts/tests/test_llm_keys.py -k "s6 or compose"` (the S3.1/S4 tests
of KEYS stay red until Tasks 11 to 13). Then `git status --short` must not list `env.runtime`,
`env.secrets` or `keycloak/aisc-realm.local.json` as changed by you.

Commit (top-level): `git add docker-compose.development.yml scripts/secrets.sh Caddyfile
env.development env.staging scripts/verify-llm-keys.sh && git commit -m "LLM keys, stage 4: the
platform gets its two secrets, the agents the internal token, the launcher hides /api/internal"`.
Put in the commit body: "Before the next `up`, run scripts/secrets.sh once: it appends the two new
secrets to env.secrets and rebuilds env.runtime."

### Task 11. The page `homepage/llm.html` (S4.1, S4.3 to S4.8)

Tests: `scripts/tests/test_llm_keys.py::test_s4_1_*, test_s4_3_* ... test_s4_8_*` (7).

New file (top-level): `homepage/llm.html`, opened as `/llm.html?project=<slug>` (Caddy's last
`handle` serves it behind `protect`; no Caddy change). Thin: all rules live in the platform.

Structure:
- `<head>`: same meta, favicon, the two `preconnect` links and the EXACT Google Fonts `<link
  href="https://fonts.googleapis.com/css2?...">` of `homepage/project.html`; one `<style>` that
  starts with a copy of project.html's first `:root{...}` block (copy it from the WORKING TREE at
  coding time: every `--var` there must be defined here), plus the header, `.session`, button, input
  and table rules the page needs (reuse project.html's selectors where they fit).
- Header like project.html: back link to `/p/<slug>` (set from JS), logo, title, and
  `<span class="session"><b id="who">&hellip;</b><a href="/oauth2/sign_out?rd=%2F">sign out</a></span>`.
- `<main>`: `<h1 id="project-name">`, a `<p id="gate" hidden>Only a platform admin manages models and
  keys.</p>`, `<section id="providers">` (heading "Providers and keys", a table body filled from JS),
  `<section id="systems">` (heading "Agentic systems", filled from JS). No `<input type="password">`
  in the static markup (build them in JS), or if there is one it has no `value=` attribute.
- Exactly ONE `<script>` element, inline, no `src`, and the text `<script` must not appear anywhere
  else in the file (comments included).

Script design (plain ES5-style functions, like project.html):
- `var slug = new URLSearchParams(location.search).get('project') || '';`
- One helper holds the only `fetch` in the file:
  `function api(path, opts) { opts = opts || {}; return fetch(path, {method: opts.method || 'GET',
  credentials: 'same-origin', headers: opts.body ? {'Content-Type': 'application/json'} : {}, body:
  opts.body ? JSON.stringify(opts.body) : undefined}); }`. Every call passes a path that starts with
  `'/api/'` as a literal string concatenated with `encodeURIComponent(...)`.
- Load order: `api('/api/projects/' + enc(slug))` -> name; then `api('/api/authz/projects/' +
  enc(slug))` -> `if (!a || !a.admin) { show gate; return; }`; only then `api('/api/projects/' +
  enc(slug) + '/llm')` and render. The first occurrence of the text `/llm` anywhere in the script must
  come after the first `/api/authz/projects/` (S4.3 compares text positions), so do not write `/llm`
  in an earlier comment or variable.
- Providers table, one row per `providers[]` entry: label, status text via `textContent`: `'key
  stored ' + p.updated_at.slice(0, 10)` when `has_key`, `'no key needed'` for `!p.key_required`,
  else `'no key'`. For `key_required` or `compatible`: a password input built with
  `document.createElement('input')`, `.type = 'password'`, `.autocomplete = 'new-password'`, never
  given a value except `''`; a "Save" button; a "Remove" button when `has_key` (or when a
  `compatible`/`ollama` row has a stored base URL). For `base_url_editable`: a text input for the base
  URL prefilled with `p.base_url` (not secret). Save sends `{api_key: ...}` and/or `{base_url: ...}`
  with method `'PUT'` to `'/api/projects/' + enc(slug) + '/llm/providers/' + enc(p.id)`; Remove
  sends `'DELETE'`. After every submit, set the key field back to `''` and re-render from a fresh
  listing.
- Systems: for each `systems[]` entry a provider `<select>`: first option value `''` text "Service
  default (environment)", then one option per provider with `p.usable` (built with
  `new Option(label, id)`); preselect `s.choice.provider` when `s.choice`. On change to a provider:
  show "Loading models..." (a status element's `textContent`), call `'/models'` on
  `'/api/projects/' + enc(slug) + '/llm/providers/' + enc(id) + '/models'`; on `d.error` show it and
  swap in a free-text model input; else fill a model `<select>` (preselect `s.choice.model`). Save:
  default -> `'DELETE'` on `'/api/projects/' + enc(slug) + '/llm/systems/' + enc(s.id)` (a 404 there
  is "already the default", not an error); a provider -> `'PUT'` with `{provider, model}`.
- Errors next to the control that caused them: `detail` when it is a string (from `d.detail`),
  otherwise a fixed text such as "Refused (HTTP 422)"; a rejected `fetch` shows exactly "The platform
  is not answering. Nothing was saved."
- Session line (P10): no `/oauth2/userinfo` call, so that every request the page makes is an
  `/api/...` one (S4.7). Set `#who` to `'admin'` once the gate passes and to `'signed in'`
  otherwise.

Regex traps in the S4 tests (all on the page's text, comments included):
- No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(` anywhere.
- No inline `on...=` attributes in markup, and in the script no `.on<letters> =` at all: this also
  forbids properties such as `.one =`, `.only =`, `.ongoing =`. Use `addEventListener` only.
- Any `X.value = ...` where `X` contains `key`/`Key` must assign `''`, and never write
  `keyX.value ==` or `===` (the regex reads `== ...` as the assigned value). Read with
  `keyInput.value.trim()`. Do not use `key`/`Key` in the names of non-key controls (base URL, model,
  provider selects).
- The script must never contain `.api_key` (send it as an object literal key `{api_key: v}`).
- Must contain: `.usable`, `/models`, `/llm/systems/`, `Loading`, `'PUT'`, `'DELETE'`, `.error`,
  `.choice`, `.detail`, `.admin`, `addEventListener`, `credentials: 'same-origin'` (once per `fetch`),
  `'Content-Type': 'application/json'`, and the texts "key stored", "no key", "no key needed",
  "Save", "Remove", "base_url", `type="password"` or `.type = 'password'`, `new-password`,
  "Service default (environment)", "Only a platform admin manages models and keys.", "The platform
  is not answering. Nothing was saved.".

Run: `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider
scripts/tests/test_llm_keys.py -k "s4 and not s4_2"` (7 passed).

Commit (top-level): `git add homepage/llm.html && git commit -m "LLM keys, stage 4: the Models and
API keys page"`.

### Task 12. The Manage menu link (S4.2), NOT committed

Test: `scripts/tests/test_llm_keys.py::test_s4_2_the_manage_menu_links_the_page_for_admins_only`
(working tree only, R5).

File: `homepage/project.html`, edited on top of the user's uncommitted change (do not revert or
reformat anything else; use exact, small edits):
- inside `<details class="menu manage" id="manage" hidden>`'s `.panel`, before
  `<span class="sep"></span>`, add `<a id="llm-settings">Models and API keys</a>` (text exactly
  that; no `href` in markup).
- in the first `<script>`, right after `if (!a || !a.admin) return;          // only an admin sees
  it at all`, add
  `document.getElementById('llm-settings').href = '/llm.html?project=' + encodeURIComponent(slug);`
  (the test regex wants exactly `getElementById('llm-settings').href = '/llm.html?project=' +
  encodeURIComponent(slug)`, and it must come after the first `a.admin`).

Run: `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider
scripts/tests/test_llm_keys.py -k s4_2`.

Commit: NONE. Record in PROGRESS.md: "homepage/project.html carries the Manage link on top of the
user's uncommitted edit; not committed; the user commits it with their change." Check with
`git diff homepage/project.html` that the user's hunks are still there.

### Task 13. Parity, pointers, full suites, cleanup

Tests: `scripts/tests/test_llm_keys.py::test_s3_1_*` (3), then everything.

1. `cmp apps/qualification/services/agents/fill/baf_llm.py
   apps/control-objectives/src/aisc_control_objectives/baf_llm.py` (no output).
2. `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider
   scripts/tests/test_llm_keys.py -k s3_1` from the root (it runs `uv run --project platform`, so
   the platform venv resolves the runtime deps of Task 1).
3. Run every suite of section 3 on the throwaway DB. All green; the only skips are the 2 + 1
   pre-existing and any S1.6 role the throwaway cannot log in as.
4. Bump the submodule pointers by explicit path (both now point at their Task 5 to 9 commits):
   `git add apps/qualification apps/control-objectives && git commit -m "LLM keys, stage 4: record
   the modules' commits (shared baf_llm, per-project model in both agents, the filler's project id)"`.
   Do not `git add` anything else (no `homepage/project.html`, no `__pycache__`).
5. `docker rm -f $NAME`; `docker ps --filter name=aisc-t-llmkeys` is empty; delete the file with the
   DB credentials.
6. Update PROGRESS.md (stage 4 row, commits per repo, what is not committed, open items) and commit
   it by path.

## 3. Full-suite commands (from 02-tests.md section 3)

On the throwaway Postgres of 0.1:

| suite | command |
|---|---|
| platform | from `platform/`: `PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform PLATFORM_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform uv run --extra dev pytest -q -p no:cacheprovider` |
| A (agents) | from a scratch directory: `A=/home/listuser/aisc-install/apps/qualification/services/agents; uv run --no-project --with-requirements $A/requirements.txt --with pytest --with httpx --with rdflib python -m pytest -q -p no:cacheprovider -c $A/pytest.ini --rootdir $A $A/tests` |
| B (control-objectives) | from `apps/control-objectives`: `CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test uv run --extra dev pytest -q -p no:cacheprovider` |
| qualification-web | from `apps/qualification`: `npx vitest run test/unit/FillerTrigger.test.ts test/unit/cardVersionsInCoreSystem.test.ts && npx tsc --noEmit` (and `npx vitest run` for the whole suite) |
| top-level | from the repo root: `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_llm_keys.py scripts/tests/test_compose.py` |

Expected end state (02-tests section 4 baselines plus the new tests, each new count including its
one guard that is already green): platform 258 passed (110 + 148) and 2 skipped, plus any S1.6 role
the throwaway cannot log in as; A 146 passed (100 + 46); B 297 passed (250 + 47) and 1 skipped;
qualification-web 25 passed in the two files and tsc clean; top-level 26 passed (5 + 21).

## 4. Decisions taken in this plan (not in 01/02)

- P1 `llm_catalogue` uses `httpx.Client(trust_env=False)` and `resolve` uses
  `ProxyHandler({})`: no proxy variable can route a key or the token elsewhere.
- P2 `resolve` follows no redirect (a 3xx is a ResolveError), like the listers (S2.17).
- P3 The models route answers 503 when a key is needed and PLATFORM_SECRETS_KEY is missing or
  malformed (01 names 503 for writes and resolves only; the page shows the detail).
- P4 `PUT .../providers/ollama` with `api_key` is 422 "ollama takes no key".
- P5 A PUT whose fields are all null is treated as empty (422).
- P6 The internal route checks, in order: forwarded, token configured, token, pid shape, system,
  project. A `compatible` choice whose base URL was later cleared resolves to 409.
- P7 Rotation counts unreadable rows and unreachable projects, never aborts, exits 0; exit 2 only on
  a missing or malformed PLATFORM_SECRETS_KEY or a bad argument.
- P8 B's per-map mapper is built from `config_for(..., fallback=<startup config>)` on every map, as
  the spec says, even when the platform has no choice (cheap; no cache, D10).
- P9 `scripts/secrets.sh --rotate` carries the existing PLATFORM_SECRETS_KEY over: rotating it
  blindly would make every stored key unreadable. Key rotation is the `llm_store rotate` procedure.
- P10 llm.html fills `#who` without a userinfo call (every literal fetch path must start with
  `/api/`).
- P11 `docker-compose.staging.yml` is not wired (spec scope is development); open item.

## 5. Tests reviewed for correctness

No test is wrong: every test in the files of 02-tests.md section 1 was read against this plan and can
pass with the code above. Some are strict in ways a coder can trip on; they are not wrong, but read
the traps before writing:

- KEYS S4.3, S4.7, S4.8 are text regexes over the whole page, comments included (Task 11 traps).
  In particular `\.on[a-z]+\s*=` rejects any property starting with `on`, and the S4.8 regex treats
  `keyInput.value === x` as an assignment. If a regex still refuses correct code, rename the code,
  do not edit the test.
- STORE `test_s1_4_the_template_file_exists_and_is_idempotent_sql` also scans SQL comments.
- CAT `test_s2_18_no_env_variable_overrides_a_hosted_url` reloads `llm_catalogue`: other modules
  must reach its names by attribute at call time.
- KEYS `test_s6_4` uses the first occurrence of `handle_path /api/*` in the launcher site.
- KEYS `test_s4_1` reads project.html's `:root` from the working tree (with the user's edit), so copy
  it from there.
- KEYS `test_s4_2` can only pass on the working tree (R5); it will fail on a clean checkout of the
  committed tree until the user commits project.html.
- platform `conftest.py` cleans the LIVE database when `PLATFORM_TEST_DATABASE_URL` is unset
  (pre-existing, not a test error, but dangerous): always set it.
