# Ledger: phase 2 report, the witness (2026-10-02)

Phase 2 of `03-coding-plan.md`, together with phase 0b (the header strip), which lives in the same
Caddy snippet. Commits on `feat/unified-modules` (aisc, local, not pushed):
- 2052896: phase 2;
- the commit that follows this report: the fixes from the review (`13-phase2-review.md`).

**Nothing is deployed.** One thing about the live stack: Caddy bind-mounts the repo's `Caddyfile`, so
its next restart loads the new file. With `LEDGER_GATEWAY` unset, a test now proves that gateway equal
to the old one apart from the intended header strip and the `/api/authz/*` block (see below).

## What was built

| Part | Where | What it does |
|---|---|---|
| witness | `platform/platform_service/ledger/witness.py`, `GET /authz/witness` in `app.py` | <ul><li>the gateway secret (401 without it, 503 if none is set);</li><li>the app from `X-AISC-App`, the project by the app's rule from the unstripped URI (or `X-AISC-Project` for the engine);</li><li>a stranger's request goes to the platform log;</li><li>the token rule below;</li><li>`record` marks, `enforce` refuses (302 to sign-in for a page load);</li><li>the record goes to Postgres `ledger.witness` (migration 0007), never to immudb, and holds no name</li></ul> |
| one token rule | `shared/identity/aisc_identity/gateway.py` | the gateway token decides and must be the gateway client's (`azp`); a Bearer token must name the same person; 30 s leeway |
| pseudonym mapping | `platform/platform_service/ledger/actors.py`, `platform/ledger-identity/0001_actor.sql`, database `ledger_identity` (in `init/project-databases.sql`) | random references per (project, person), MAC-checked rows, real erasure, a connection pool; in its own database, closed to pgAdmin's read-everything role (S8) |
| gateway | `Caddyfile` | <ul><li>`strip-and-sign-in` (phase 0b);</li><li>`protect <app>` and `protect-reads <app> <paths>`, each wrapped in `route` so the order holds;</li><li>`witness-{$LEDGER_GATEWAY:off}`;</li><li>the admin and schema checks inside protect's `route`;</li><li>the launcher returns 404 for `/api/authz/*`</li></ul> |
| compose | `docker-compose*.development.yml` | <ul><li>Caddy: `LEDGER_GATEWAY` (default `off`) and the gateway secret;</li><li>platform: the ledger settings and the public signing key;</li><li>oauth2-proxy: `--cookie-refresh=4m`</li></ul> |
| secrets | `scripts/secrets.sh` | the gateway secret, three caller tokens, `PLATFORM_RW_PASSWORD` |
| `platform_rw` password | `init/platform-role.sql` (applied by postgres-setup), `PLATFORM_DATABASE_URL` | generated instead of the role's own name (review M1) |

## Tests (`LEDGER_TESTS_REQUIRED=1`: a skip is a failure)

| Suite | Result | Skips |
|---|---|---|
| ledger phases 1 and 2 (`test_ledger_{canonical,naming,registry,secrets,store,provision,cleanup,pool_cli,witness,actors}.py`) | 320 passed | 0 |
| `shared/identity` | 36 passed | 0 |
| repo (`test_ledger_{caddy,caddy_equivalence,gateway,credentials,pool_script}.py`, `test_{compose,platform_role_password,secrets_hardening,immudb_hardening}.py`) | 131 passed | 0 |
| platform suite without `tests/ledger` | 579 passed, 1 failed, 2 skipped | 2 (pre-existing) |

**How the tests were checked.** Four rules were broken on purpose and the witness suite caught each:
- the secret check;
- `azp`;
- the two-token rule;
- the stranger rule.

The equivalence test was also broken on purpose (one upstream port) and caught it.

**The real-Caddy suite** runs in three modes: on, off, and **unset**. It now includes a 403 from the
admin check, and the check that the admin and schema gates see the person's token. That last check
caught a bug in the first version of the design: a `route` sorts after `forward_auth`, so
`admin_only` would have run before sign-in and locked every admin out.

**Known failures, not caused by phase 2:**
- `test_project_system.py::test_i17_1_...` failed once in the full run with "never opened". The
  statistics collector didn't report a session within its 5 s window under load. It passes 3 runs out
  of 3 alone, its "no lingering session" half passed, and phase 2 doesn't touch card versions.
- `test_targets_sync.py::test_tg2_...` is flaky, as recorded in phase 1. It passed this time.
- `scripts/tests/test_llm_keys.py::test_s3_1_...`: the two `baf_llm.py` copies have diverged (phase 1
  report).
- The later phases' ledger files are red by design (relay, outbox, beacon, privacy and so on).

## Drills

| Drill | How | Result |
|---|---|---|
| platform stopped: writes refused, reads served | real caddy:2.10.2, platform stopped (stub upstreams) | with the witness on, a GET passes and a POST gets 502; with it off or unset, both pass |
| token at the edge of expiry | unit tests on the shared rule (15 s past expiry passes, 60 s refused) and on the witness | passed |

Both still need a run on the real stack with `record` on: real oauth2-proxy, Keycloak and the platform.
That run is the first step of the deploy below.

## Deviations, with owners
- **TypeScript twin of the token rule, and the apps' own use of it**: phase 5 for TypeScript, each
  app's own phase otherwise. Until then the witness applies the rule before any app sees the request.
- **The caller tokens** (engine, dashboard, agents) are held by the platform only, until each caller's
  phase. The engine's must go to a process that never imports plugins (decision D12, phase 8).
- **Start-up refusal on a bad mode pair**: phase 2 answers 503 per request instead. It moves to the
  phase 4 deploy checklist.
- **Rotating the gateway secret with an overlap**: phase 4.

## Recorded for later (from the re-review, `15-phase2-rereview.md`)
- **m7, the case and percent-encoding of paths.** Caddy's `handle /qualification*` ignores case, and
  the apps decode percent-encoding; the witness's project rules do neither. A request to
  `/qualification/p/%6Dcas/...` reaches project `mcas` while its witness record goes to the platform
  log. This fails safe (the event will be rejected), and phase 3's relay must pin it with a test.
- **m9, `env_file:` services.** The credentials test reads `environment:` blocks only; controls and
  control objectives also take variables from `env_file:`. Phase 8 moves the test onto
  `docker compose config` output.
- **m10, the signing key's public half.** If `immudb-signing.pub` doesn't exist when the platform
  starts, Docker creates a root-owned directory at that path, and a later `secrets.sh` then can't
  write the file. Run `scripts/secrets.sh` before any `up`, which the deploy order does. If the
  directory was made by mistake, remove it (`sudo rmdir immudb-signing.pub`) and run `secrets.sh`.

## To deploy, when you say so (in this order)
1. `scripts/secrets.sh`. Already run here: it only adds what's missing.
2. `postgres-setup`: applies the new `platform_rw` password and creates `ledger_identity`. **Then
   recreate `platform` straight away** (the image needs a rebuild: `ledger-identity/` and the new
   code): the running platform keeps its open sessions, but no new connection works until it uses
   the new password.
3. Recreate `oauth2-proxy` (4-minute refresh) and reload Caddy. Its witness stays off until
   `LEDGER_GATEWAY=on`.
4. Turn on `LEDGER_MODE=record` and `LEDGER_GATEWAY=on`. Then run the two drills on the real stack: stop
   the platform and check that writes are refused and reads served; leave a token close to expiry and
   check that a write still passes.
