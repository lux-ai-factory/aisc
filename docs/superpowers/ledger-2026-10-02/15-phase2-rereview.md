**Verdict: 0 blockers, 0 majors open, 4 minors (1 introduced by the fixes), 4 nits. Deploy aside, phase 2 can be called done once the minors are recorded. None of them blocks it.**

# Phase 2 fix review (696af6c)

I didn't edit anything in the repo. Tests ran against my own throwaway Postgres and immudb (`aisc-t-rev8-f1a7b2-*`), with `init/platform-role.sql` applied and a generated password. I also ran caddy containers named `aisc-t-rev8-*`. All of them have been removed, and nothing touched project `aisc`.

## 1. M1: platform_rw password (closed)

- **The SQL works.** I applied `init/platform-role.sql` with `-v platform_rw_password=<hex>`. A login from the host as `platform_rw:platform_rw` was then refused (OperationalError), and the generated password was accepted. Running the file again without the variable changes nothing, as the `\if :{?...}` guard intends.
- **Wiring is consistent.** `scripts/secrets.sh` makes `PLATFORM_RW_PASSWORD=rand`, which is hex and so safe inside a URL. `postgres-setup` gets the variable, the bind mount and the psql step. The platform's `PLATFORM_DATABASE_URL` is now required (`:?`), not a default. `env.runtime` and `env.secrets` already contain the key; I checked that it is present, not its value.
- **Deploy order works.**
  - `platform` has `depends_on: postgres-setup: service_completed_successfully`. Both files are in one project, so `up -d platform` reruns `postgres-setup` first even if someone skips step 2.
  - The only gap is between step 2 and the platform's recreation. The old platform keeps its open pooled sessions, but any new connection fails. Recreate it right after step 2.
- **No other runtime client breaks.**
  - No other compose service, in any compose file, logs in as `platform_rw`.
  - The isolate tool connects as superuser and uses `SET ROLE platform_rw`.
  - `projectdb`, `llm_store` and `db.py` build project DSNs with `make_conninfo(dsn(), dbname=...)`, so the password carries over.
  - `scripts/lib/report_bed.py` and `apps/qualification/test/db/throwaway-db.sh` use their own throwaway clusters.
  - `verify-db-access.sh` runs `docker exec postgres psql ...@localhost`, and the image's `pg_hba` trusts 127.0.0.1. The password is never checked there, so the change is harmless (and has no effect).
- **The default DSN in `platform_service/db.py` (`platform_rw:platform_rw@postgres`) is not a problem.**
  - Compose always sets the URL now, so the default only applies outside compose.
  - After the deploy it fails closed, because that password no longer logs in.
  - A side benefit: `platform/tests/conftest.py`, which defaults to the live database at `127.0.0.1:5432`, will stop reaching it.

## 2. M2: ledger tokens (closed)

- In all three compose files, only `platform` holds `PLATFORM_LEDGER_{ENGINE,DASHBOARD,AGENTS}_TOKEN`.
- `HOLDERS` is now `{"platform"}` for each token and covers `LEDGER_IMMUDB_PASSWORD`. `RUNS_PLUGINS` now includes `aisc-backend`. YAML merge keys (`<<: *backend-env`) are resolved by `safe_load`, so the test does see `aisc-backend`'s inherited environment.
- D12 is in the spec as open for phase 8.
- **Minor (n3):** the T17 row in `02-spec.md` gained the note, but its old sentence remains: "Worker results reach the ledger through the engine backend, which holds the engine's token." That now contradicts D12 and should be reworded.

## 3. New tests: all pass, and wrong versions fail

Results: 54 passed in `tests/ledger/test_ledger_{actors,witness}.py`, and 69 passed in `scripts/tests/test_ledger_{credentials,caddy_equivalence,gateway}.py` plus `test_platform_role_password.py`, with `LEDGER_TESTS_REQUIRED=1`.

I broke each fix on purpose, without editing the repo:

| Broken on purpose | Result |
|---|---|
| `actors._connect` back to one `psycopg.connect` per call | pool test fails (`51 - 31 <= 4`) |
| `actor_name` column added to `ledger.witness` | column test fails |
| same column renamed to `person` | column test **passes** (nit: it checks a list of banned names; listing the allowed columns would be stronger) |
| one upstream port changed | equivalence test fails |
| a `request_header -X-Auth-Request-User` added before a proxy | equivalence test fails |
| launcher `/api/authz/*` changed from `respond 404` to `reverse_proxy platform:8000` | **equivalence test hides it**; `test_the_launcher_never_serves_the_witness` catches it |
| strip moved after `forward_auth` in `strip-and-sign-in` (deletes oauth2-proxy's identity headers) | **equivalence test hides it**; `test_the_admin_and_schema_checks_run_after_sign_in` catches it |

**Minor (n2): the equivalence normalizer is too permissive.**
- `_is_authz` drops any route matching `/api/authz/*`, whatever it does.
- `_is_strip` drops a strip wherever it sits.
- Both hidden changes above are caught by other suites today, but this test alone would pass them. Tighten it: drop the authz route only if its handler is a static 404, and drop a strip only where it comes right before the `forward_auth`.
- Nit: flattening subroutes that have no matcher also throws away `group` and `terminal` on the inner routes.

Other checks:
- **Admin 403 test:** if the gate is skipped, the response is 200 and pgAdmin receives the request, so the test fails. It is meaningful.
- **`test_platform_role_password.py`:** text checks only. The SQL itself is correct, as I verified in section 1. Nit.
- **Nit:** `aisc-backend-migrate` uses the same image but is not in `RUNS_PLUGINS`. The exact-holders test still covers it for every credential it lists.

## 4. New issue, and review items still open

- **Minor (n1), introduced by the m3 pool fix** (`actors._connect`):
  - If `migrate()` raises, the new `ConnectionPool` is neither stored nor closed. Every later witnessed write builds another one, so connections and pool threads leak.
  - If `ledger_identity` can't be reached, `pool.connection()` waits for psycopg_pool's default 30 s timeout. Before, the error was immediate. Each write would hang about 30 s before the 500.
  - Fix: close the pool on failure, and give the pool a short `timeout`.
- **Minor (n4): not fixed and not recorded.**
  - **m7**, the case and percent-encoding mismatch in the witness path rule: no test pins it, and neither the report nor the spec mentions it.
  - **m9**, the `env_file:` blind spot: still there.
  - **m10**, the signing key: the commit claims m10 is documented, but only the "run `secrets.sh` first" half is in the report's deploy order. The `immudb-signing.pub` root-owned-directory failure is not mentioned.

**Before calling phase 2 done:** fix or record n1 to n4. Reword the T17 row, and record m7, m9 and the signing-key half of m10 in `14-phase2-report.md`.
