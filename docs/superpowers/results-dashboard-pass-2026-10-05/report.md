# Results dashboard: debugging, refactoring, linting and documentation pass (2026-10-05)

All 8 steps on `apps/results-dashboard`, our overlay only (`aisc_ext/`, `superset_config.py`,
`scripts/`, Dockerfile, compose and env files). Superset's own code was not read; only its version was
checked against public advisories. On `feat/unified-modules`; the local stack runs the result.

The 16 results-dashboard commits named below were squashed into one, `5640b97`, before the push. The
originals are on the local branch `backup/dashboard-pass-2026-10-05-presquash` of that repo; the short
hashes in the tables are theirs. The aisc commits keep theirs.

## Before and after

| Check | Before | After |
|---|---|---|
| Unit tests (README command) | 3 modules failed to import (no pyyaml) | 255 passed, 23 skipped (the database tests) |
| With the database and outbox tests (throwaway Postgres) | 236 + 22 | 278 passed |
| SSO tests inside the image | 7 passed (4.1.1) | 7 passed (4.1.4) |
| ruff (default rules) | 13 findings | clean |
| Superset | 4.1.1 | 4.1.4; `check-superset-upgrade.sh` held every check in a browser |

## Security

| # | Finding | Outcome |
|---|---|---|
| S1 | High: `dashboard_ro`'s password is its name; plugin code could read every project's results | Fixed: generated (aisc `acaeda4`), the bridge takes it from the environment only (`2b7718b`). Live: old password refused over the network; mcas re-registered, its connection logs in |
| S2 | High: review-request API listed, created and resolved across projects; CSRF-exempt | Fixed `1876976` |
| S3 | Superset 4.1.1 CVEs | 4.1.4 (`0112724`): fixes CVE-2025-27696. **Needs your decision:** CVE-2025-55672/55674/55675 (fixed 5.0) and CVE-2026-23980/23982/23984 (fixed 6.0) need a major upgrade |
| S4 | Plugin metadata reaches chart labels (stored XSS in 4.1.1) | Fixed `03bc738`: markup and control characters refused, lengths capped |
| S5 | Guest tokens signed with Superset's published default | Fixed `43ee432` + aisc `b185f00` |
| S6 | OIDC client secret fallback | Fixed `43ee432` |
| S7 | Authlib unpinned | Pinned with the others (`0112724`) |
| V | Raw Comments / Review Requests tables visible to viewers | Fixed `ac03d26` |
| F | `X-AISC-Request-Id` accepted from direct callers on port 8189; the gateway does not check the token audience; Superset's metadata DB connects as the Postgres superuser; connections are named by slug | Follow-ups: cross-module (gateway, platform relay, infra) |

## Code review

| # | Finding | Outcome |
|---|---|---|
| R1 | Every comment and review write on a plugin dashboard was refused (slug `aisc-<hex>-<plugin>` unknown to the ledger), and the platform's witness had the same gap | Fixed `4e6a05b` + aisc `51a017b` |
| R2 | Review-request API cross-project | = S2 |
| R3 | A Save-as copy of a default chart was deleted at the next sync | Fixed `e3ff0a7` |
| R4 | Raw tables visible to viewers | = V |
| R5 | Two workers could deliver the same outbox rows | Fixed `38190e3`: advisory lock (proven on Postgres) |
| R6 | Shipped `dashboard_ro`, OIDC and admin passwords | = S1, S6, `5c335dd` |
| R7 | The audit clerk defaulted to `immudb` and only printed when off | Fixed `114a74f` |
| R8 | `bootstrap.sh` failed on a fresh checkout | Fixed `5c335dd` |
| R9 | The login redirect dropped `next`'s query | Fixed `43ee432` |
| R10 | Writes waited for the platform (up to 5 s) | Fixed `dc1447b` |

Also: `.env.example` set `IMMUDB_PASSWORD` twice and the README's test command lacked pyyaml
(`1ab58bd`); lint and one `projects` fixture in `tests/conftest.py` (`5851299`); README (`184aea0`).

## Deployed on the local stack

The Superset metadata database was backed up first (scratchpad `superset-before-4.1.4.dump`). Then
`dashboard`, `dashboard-migrate` and `platform` were rebuilt, postgres-setup was rerun (new
`dashboard_ro` password), Superset's migrations ran to 4.1.4, and mcas was re-registered through the
bridge. `scripts/secrets.sh` added `DASHBOARD_RO_PASSWORD` and `SUPERSET_GUEST_TOKEN_SECRET`. Health
200, the gateway answers (302 to sign-in), and the project connection logs in as `dashboard_ro`.

## Still open

- The major Superset upgrade (5.0 / 6.0) for the advisories above.
- The follow-ups F above.
- `engine_rw`, `controls_rw`, `catalogue_rw` and `report_composer_rw` still use their own name as password.
- A signed-in view of a tile was not checked (no browser in this session); the upgrade check covered
  tiles in a browser on throwaway containers.
