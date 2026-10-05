**Verdict: 0 blockers, 2 majors, 13 minors. Phase 2 is not done yet.** The code works and the live Caddy can safely load the repo Caddyfile as it is. Three things keep it from being done: the two majors below, the two DoD drills that have not been run, and the missing phase 2 report.

## What I checked

Commit 2052896 on feat/unified-modules, compared with its parent. I made no repo edits and touched nothing on the live stack. I used my own containers named aisc-t-rev7-*, and all of them have been removed.

- **Witness and gateway tests:** `test_ledger_witness.py` and `test_gateway.py` gave 57 passed, 0 skipped. The full `shared/identity` suite gave 36 passed.
- **Caddy suites:** `test_ledger_caddy.py`, `test_ledger_credentials.py` and `test_ledger_gateway.py` (real caddy:2.10.2, `LEDGER_TESTS_REQUIRED=1`, all three modes on/off/unset) gave 67 passed. The suite cleaned up all aisc-t-gw-* containers.
- **Person mapping tests in `test_ledger_privacy.py`:** 5 passed (S8 grants, the two concurrency cases, the platform scope, pid case). 3 failed (changed name, swapped row, erasure). They fail inside the phase 3 `rate()` fixture (`ledger.emit` is missing), so they are red by design.
- **MAC and erase, checked by hand:** I called `actors` directly. An edited name raises `MappingAlarm`. A row moved to another scope raises `MappingAlarm`. A rename keeps the MAC valid. A pid in upper case resolves. `erase` deletes the row and `resolve` then returns None.
- **Caddy equivalence:** I ran `caddy adapt` on the old and new Caddyfile with the live caddy's exact environment (no `LEDGER_GATEWAY`), then flattened the handler trees and compared them.
- **Compose equivalence:** I ran `docker compose config` on the old and new compose files (my own project name, render only) and compared environment keys per service.
- **Launcher block:** I sent path variants of `/api/authz/witness` to a throwaway Caddy.
- **Not reproduced:** the full platform suite without `tests/ledger`. It was still running at my 590 s limit.

## 1. Witness correctness against the spec

The witness logic follows the spec:

- **Secret check:** constant-time compare. An absent, empty or wrong secret gives 401 and writes no record, even in `record` mode. No secret configured gives 503.
- **App name:** `X-AISC-App` must be one of `GATEWAY_APPS`, and the original URI must start with `/`. Otherwise 400.
- **Project per app:** taken from the unstripped URI by `APP_PROJECT_RULES`, or from `X-AISC-Project` for the engine. It is resolved with `db.get_project`.
- **Member or stranger:** a stranger's record gets `pid=None` and `member=false`, and its `actor_ref` is in the platform scope. An unknown pid creates nothing.
- **One token rule:** the gateway token must verify with `azp == aisc-gateway`. A Bearer token, if present, must verify and carry the same `sub`. Its `azp` is not checked.
- **Leeway:** 30 s, applied by PyJWT to both `exp` and `nbf`.
- **Record and enforce:** `enforce` refuses with 401, or with a 302 to `/oauth2/start?rd=<quoted original>` when `Sec-Fetch-Dest: document`. `record` passes the request through and records it as unverified with a short reason code. The reason never contains token text.
- **Query string:** kept only as `query_hmac` (the HMAC key is chosen after the project is known). `route_path` holds no query.
- **No people in the record:** no `sub` or name. Only `actor_ref`, `token_jti` and `token_exp`.
- **immudb:** never on the request path. The record is written to Postgres `ledger.witness`.

Issues:

- **(m3) Unpooled connection per request.** `actors.ref_for` opens a new `psycopg.connect` to `ledger_identity` on every witnessed request, with SCRAM authentication each time. The witness path is therefore two pooled queries, one fresh connection and one insert, which is well above the spec's "about 1 ms". It also adds connection churn under bursts. A small pool for `ledger_identity` would fix it.
- **(m4) No start-up refusal (spec 5.1).** The spec says the platform refuses to start in `record` or `enforce` without the gateway secret. The code answers 503 per request instead. Nothing guards against the disallowed pair (`LEDGER_GATEWAY=on`, `LEDGER_MODE=off`): writes pass with no id and nothing is logged.
- **(m5) No secret rotation.** `ROTATION_OVERLAP` is defined but unused. The witness accepts exactly one gateway secret, so rotating it means a window where every write is refused.
- **(m6) Interface drift from spec 6.1.** The spec gives `witness(*, headers, mode, now) -> WitnessResult(status, request_id, record)`. The code has `witness(headers) -> Answer(status, headers)`. The spec should be updated to match.
- **(m7) Path rule versus how apps match paths.** Caddy's `handle /qualification*` matches without regard to case, and the apps decode percent-encoding. The witness regexes do neither. A member who sends `/qualification/p/%6Dcas/...` reaches project `mcas`, but the witness record goes to the platform log. This fails safe, and the phase 3 relay check (spec 4.2, project equality) must catch the mismatch. A test should pin it.
- **(m11) `record` mode fails closed on database errors.** If `ledger_identity` is missing or the insert fails, the witness returns 500 and Caddy refuses the write, even in `record`. That fits spec 5.3 ("platform down: writes fail") but should be stated, because `record` is meant to be the safe mode.

## 2. The person mapping in `ledger_identity` (S8)

- **S8:** `init/project-databases.sql` creates the database owned by `platform_rw`, revokes everything from PUBLIC and grants CONNECT only to `platform_rw`. The S8 test checks CONNECT, through role membership, for `inspector_ro` and every module role, and checks that no mapping table exists in `platform`. It passes. pgAdmin connects only as `inspector_ro` (pgpass in compose).
- **Uniqueness:** `UNIQUE (scope, sub)`, with the platform scope stored as the text `'platform'` rather than NULL. `INSERT ... ON CONFLICT DO NOTHING` plus a re-select inside the same READ COMMITTED transaction is correct, and the six-thread test passes for both scopes.
- **MAC:** keyed per project and covering reference, sub and name. Verified correct (see above).
- **Erase:** deletes the row, and references are random, so the link is really gone.
- **Migration on first use:** done under a lock and a per-DSN memo, through `migrate()`, which creates the `identity` schema. `platform` depends on `postgres-setup` completing successfully, so the database exists before first use.
- **Dockerfile:** copies `ledger-identity/`.
- **(M1, major) Weak `platform_rw` password.** `platform_rw`'s password is its own name. `init/platform-db.sql` creates every module role with password = role name, `report-roles.sql` resets only `report_ro`, `report_composer_rw`, `inspector_ro` and `connector_rw`, and `PLATFORM_DATABASE_URL` is absent from `env.runtime`, so the default `platform_rw:platform_rw` applies. `aisc-eval-worker`, which runs plugin code, is on the `backend` network with `postgres:5432`. Plugin code can therefore:
  - read every name in `ledger_identity`;
  - delete mapping rows (an unauthorised erasure);
  - insert forged `ledger.witness` rows with any `actor_ref` or project.

  The weak password predates phase 2, but phase 2 makes it the only thing guarding S8 and the witness table, which is what T17 is about. Possible fixes:
  - a generated `platform_rw` password in `secrets.sh`, applied by `postgres-setup` the way `report_ro` is, and set through `PLATFORM_DATABASE_URL`;
  - a dedicated `ledger_identity` role with a generated password;
  - keeping the worker off the network that reaches Postgres.

  The relay's later checks reduce the damage from forged witness rows, but nothing reduces the exposure of the names.
- **(m12) Phase 2 mapping behaviour has no green test of its own.** The MAC alarm and erasure tests only run through the phase 3 `rate()` fixture. Phase-level tests that call `actors.ref_for`, `tamper`, `resolve` and `erase` directly should be added.

## 3. Caddy safety on the live stack

**The live Caddyfile can be loaded as it is.** The live caddy (caddy:2.10.2) bind-mounts the repo Caddyfile and its environment has no `LEDGER_GATEWAY` and no `AISC_WITNESS_GATEWAY_SECRET`. `{$LEDGER_GATEWAY:off}` selects the empty snippets, and `witness-on` is never parsed, so the missing secret does not matter. The adapted JSON, compared handler by handler, matches the old file exactly, except for two intended changes:

- **The header strip:** 14 occurrences, one per protected handle, each placed immediately before the oauth2-proxy `forward_auth`.
- **The new launcher block:** `handle /api/authz/* -> 404`, placed before `handle_path /api/*`.

What stayed the same:

- The pgAdmin and schema gates still run oauth2-proxy and then `/authz/admin` or `/authz/schema`, in that order. The extra nesting in `route` changes nothing.
- On `/p/*` and `@platformProjects`, `root` and `rewrite` still run before sign-in, as before. That means `rd=/project.html` on a 401 redirect is old behaviour, not new.
- The `file_server` handles, `/api/v1/internal/* -> 403`, the `oauth_endpoints` on all three sites, and the dashboard site are unchanged.

On the throwaway Caddy, `/api/authz/witness`, `//authz`, `%61uthz`, `AUTHZ`, `/./`, `/API` and `authz%2f` all returned 404, and the platform stub received none of them.

One condition: this holds for a `docker restart caddy` or a reload. A `docker compose up` that recreates caddy needs `AISC_WITNESS_GATEWAY_SECRET` in `env.runtime`. Locally it is there.

What the real-Caddy suite proves:

- The "on" half proves the order (sign-in, then witness), the app name, the unstripped URI, the secret, the 302 pass-through, listed reads, that duplicate `@witnessed_launcher` matcher names load, and that platform-down gives 502 only when the witness is on.
- The off and unset halves prove only that the witness is not called. They do not prove equivalence with the old file.
- **(m13)** The adapt comparison I ran (old file versus new file, ignoring the strips) would make a cheap, strong test of that equivalence.
- **(m14)** The pgAdmin and schema test checks that the admin gate saw the token, but the stub always answers 200, so a 403 from the gate blocking pgAdmin is never exercised.

## 4. Compose and secrets

- **x-backend-env restructure:** rendered config confirms it. `aisc-backend` gains only `PLATFORM_LEDGER_ENGINE_TOKEN`. `aisc-backend-migrate` and `aisc-eval-worker` are unchanged.
- **New environment keys:** caddy gets 2, platform 10, dashboard 1 and qualification-agents 1. oauth2-proxy has only `--cookie-refresh=4m`, and the realm's `accessTokenLifespan` is 300, which is consistent. platform also gains the public key mount.
- **(M2, major) T17 is false for the engine backend.** `aisc-backend` imports plugin packages in its own process: `routers/plugin.py` calls `plugin_loader.load_plugin` and `load_package`, which use `importlib.import_module` in `shared/plugin-manager/.../loader.py`. It now holds `PLATFORM_LEDGER_ENGINE_TOKEN`, so plugin module code runs alongside a ledger token. Test K passes only because `RUNS_PLUGINS` leaves out `aisc-backend`. The token is not used before phase 8.
  - Mechanical fix: stop handing out the three caller tokens until phases 5, 8 and 9 need them.
  - Decision needed: either accept this as a stated residual risk in spec section 10, or move the engine's posting into a process that never loads plugins. That decision is the user's.
- **(m9) Test K's blind spots:**
  - it reads raw YAML, so values from `env_file:` (controls, control-objectives) are invisible;
  - `LEDGER_IMMUDB_PASSWORD` has no holder rule;
  - it would be stronger on `docker compose config` output.
- **(m10) Failure modes:**
  - On an `env.runtime` made before this commit, the `:?` checks make every compose command over these files fail, including ones for unrelated services. `secrets.sh` without `--rotate` adds the missing values, so the deploy steps should say to run it first.
  - If `immudb-signing.pub` is missing, Docker creates a root-owned directory at that path, and a later `secrets.sh` then fails to write the file.

## 5. Would the tests catch a wrong implementation?

Mostly yes:

- W2 counts records.
- W3 covers every kind of bad token on both modes, and the leeway on both sides: 15 s past expiry passes, 60 s past is refused.
- W4 covers five path rules plus the header rule, the stranger rule and the ghost pid.
- G uses real Caddy with echoing stubs that log what they receive.
- C2 now checks that each gate sits inside protect's `route`.

Gaps:

- **(m8)** The "no subject, no name" test reads only `_FIELDS`, so a `sub` or name column added to the table would not be caught. A check on the table's actual columns would be.
- No test covers the `launcher` `/p/{slug}` rule, an engine write without `X-AISC-Project`, or the `rd` encoding of a query string.
- W6 is close to vacuous, because the witness never touches immudb in the first place.
- Nothing was skipped in the runs I made.

## 6. DoD items not met, and deviations

- **Drills not run.** Phase 2 lists two:
  - "platform stopped: writes refused, reads served". G covers this with stubs only. It has not been run against the real platform.
  - "a token at the edge of expiry". Only unit tests cover the leeway. No drill was run through real oauth2-proxy and Keycloak.

  There is no phase 2 report recording these or the skip counts.
- **Full platform suite:** not confirmed green by me (timed out).
- **(m1) The TypeScript twin of `gateway_identity` is missing.** The coding plan's phase 2 row asks for "Python + TS". No `shared/identity-ts` exists, and no app, the platform's own `caller_from_headers` included, uses the shared rule yet. That is acceptable while `enforce` is off, but the plan should record it as a deviation with an owner (phase 5 for TypeScript; each app's own phase for adoption).
- **(m2) This review** is the independent review the DoD requires, and it leaves two majors open.

## Minor owners (suggested)

| ID | Item | Owner |
|---|---|---|
| m1 | TypeScript twin and app adoption | phase 5 |
| m3 | Pool for `ledger_identity` | phase 2 follow-up |
| m4 | Start-up guard on mode pairs | phase 2 |
| m5 | Secret rotation overlap | phase 4 |
| m6 | Spec 6.1 text | spec |
| m7 | Path case and encoding test | phase 3 relay |
| m8 | Table column test | phase 2 |
| m9 | Test K on rendered compose config | phase 8 |
| m10 | Deploy notes | phase 2 report |
| m11 | State `record`'s fail-closed behaviour | spec 5.3 |
| m12 | Direct mapping tests | phase 2 |
| m13 | Adapt-equivalence test | phase 2 |
| m14 | Admin-gate 403 stub | phase 2 |

## To call phase 2 done

1. Fix or decide M1 (generated `platform_rw` password, or a dedicated role).
2. Fix or decide M2 (drop the caller tokens until they are needed, and record T17's scope in the spec).
3. Run both drills and write the phase 2 report, including the skip counts and the TypeScript twin deviation.
4. Add the m12 and m13 tests. They are cheap and they close what this review had to check by hand.
