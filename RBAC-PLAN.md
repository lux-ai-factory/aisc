# Authorisation plan

> **Built.** Waves 1 to 6 are done, test-first, and `scripts/verify.sh` runs
> them: 16 ok, 0 failed. `scripts/verify-rbac.sh` (40 assertions) is the
> standing proof against the running stack. Wave 0 is the one item left, and it
> is not code: the parallel stacks still publish their backends on 0.0.0.0.
> What each wave actually turned into is noted under it.

Where we are: authentication is enforced (oauth2-proxy is the only published
door in the `aisc` stack, every module backend is internal), and authorisation
is not. Two endpoints check a role (`me.py:24`, `audit.py:49`). Everything else
treats "signed in" as "allowed".

Two things are being fixed, and they are different:

* **Capability**, which is a property of the account: may this person install
  code, publish to the catalogue, read the audit log, administer dashboards.
  This stays a Keycloak realm role (`admin`, `primary-user`).
* **Membership**, which is a property of an account *in a project*: owner,
  editor, viewer. This is data, in `core.project_member`, because it is
  per-project and would explode the realm if it were roles.

Rule for the whole plan: the decision logic lives in Python, so it can be read
and tested in one language. The two Next apps get a thin check that asks a
Python endpoint, and no policy of their own.

Every wave is test-first: write the failing test, watch it fail for the right
reason, then make it pass.

---

## Wave 0. Close the doors that bypass the gateway (no code)

Not RBAC, but it invalidates everything below if left alone. The `og-*`,
`aisc-sandbox-*`, `aiscv-*` and `tsb-*` stacks publish their backends on
`0.0.0.0` with no proxy in front: `og-aisc-backend` 8000, `og-catalogue-backend`
8010, `og-postgres` 19432, and more.

* Do: stop the stacks that are not in use; for any that must keep running,
  change their published ports to `127.0.0.1:`.
* Done when: `docker ps --format '{{.Names}}\t{{.Ports}}'` shows no `0.0.0.0`
  binding except the `aisc` stack's Caddy and Keycloak.

---

## Wave 1. Admin-only code paths (the one that matters most)

The catalogue is writable by any account, and the engine installs and runs what
is in it. That turns "has a login" into "runs code on the server".

**Test first** (`apps/catalogue/backend/tests/test_write_needs_admin.py`):

1. Every unsafe method on the app returns 403 with no token, and 403 with a
   `primary-user` token. Enumerate from `app.routes`, do not list them by hand,
   so a route added later fails the test by existing.
2. The same calls with an `admin` token reach the handler (2xx, or 404/422 for
   a made-up id, never 401/403).
3. GET stays open to any signed-in account.
4. `/health` and `/docs` stay open.

Same shape for the engine (`apps/backend/.../tests/test_plugin_admin_only.py`):
`POST /plugins`, `POST /plugins/refresh`, `DELETE /plugins` refuse a
`primary-user` token.

**Then build:**

* `apps/catalogue/backend/authz.py`: an ASGI middleware that denies every
  unsafe method by default and allows it only for a verified `admin`, with a
  small explicit allowlist. Default-deny, so no endpoint can be forgotten. It
  covers `main_api.py` and `devpi_api.py` (`/upload`, `/remove`) together.
* `apps/backend/aisc_backend/routers/plugin.py`: `auth=require_role("admin")` on
  the three write routes.

**Done when:** `pytest apps/catalogue/backend/tests -q` and the engine suite are
green, and against the running stack a `primary-user` token gets 403 from
`POST /tool/` and from `POST /api/v1/plugins`.

---

## Wave 2. One identity library for the Python services

Right now only the engine can verify a token. `platform`, `catalogue` and
`control-objectives` cannot say who is calling, so they cannot enforce anything.

**Test first** (`shared/aisc_identity/tests/`): a verified token yields subject,
email and roles; an expired or wrong-issuer token raises; the
`X-Auth-Request-Access-Token` header is read when there is no `Authorization`;
with `AUTH_ENABLED=false` a fixed development identity is returned so local work
does not need Keycloak.

**Then build:** `shared/aisc_identity/` with `verify_token`, `get_roles`,
`caller_from_headers`, and FastAPI dependencies `caller()` and
`requires_role("admin")`. Lift the body out of
`apps/backend/aisc_backend/auth/keycloak.py`; the ninja adapter there keeps
working and simply calls into it. Wave 1's middleware moves onto it.

**Done when:** the engine suite still passes unchanged, and the new package has
its own green suite.

---

## Wave 3. Membership as data

**Test first** (`platform/tests/test_membership.py`): creating a project makes
the creator its owner; `GET /projects` returns only the caller's projects;
`admin` sees all; a non-member gets 404 (not 403, which would confirm the
project exists); an owner can add and remove members; an editor cannot; the last
owner cannot be removed.

**Then build:**

* Migration: `core.project_member (project_id, subject, email, role, added_at)`
  with `role in ('owner','editor','viewer')`, unique on `(project_id, subject)`,
  and `core.project.created_by`.
* Backfill: every existing account becomes owner of every existing project. This
  is a single-tenant install and nobody should lose access on the day it lands.
* `platform_service/app.py`: every endpoint takes `caller`, list and get filter
  by membership, create records the owner, plus `GET /projects/{slug}/members`,
  `POST`, `DELETE`.
* `GET /authz/projects/{slug}` returning `{"role": "owner|editor|viewer|null"}`.
  This is the one call the TS apps will make.

**Done when:** `pytest platform/tests -q` green, and the launcher signed in as
`user` shows only the projects that account belongs to.

---

## Wave 4. Enforcement in the modules

Per module, the same two questions: may this caller see this project at all, and
may they change it. Read needs any membership, write needs editor or owner.

* **Engine** (Django-Ninja). Test first: a viewer gets 403 from `POST /projects`,
  `POST /evaluations/task`, `PUT /datasets/{pid}/data`; a viewer gets 200 on the
  corresponding reads; a non-member gets 404 on a project they do not belong to.
  Build: one `membership_for(request, platform_project_id)` helper querying
  `core.project_member`, used by the project-scoped routes. `internal.py` keeps
  its worker credential and is not affected.
* **control-objectives** (FastAPI). Same tests against its project routes, using
  the wave 2 dependencies.
* **controls and qualification** (Next). One `middleware.ts` each: read the
  gateway headers, call `GET /authz/projects/{slug}`, 404 the whole `/p/{slug}`
  subtree for a non-member, and refuse unsafe methods for a viewer. Plus one
  re-check in the server action that writes, so the middleware is not the only
  guard. About forty lines of TS in total and no policy in it.
* **Launcher** (`homepage/project.html`): hide the cards for modules the caller
  cannot enter, and show the role. Cosmetic, after the server side is real.

**Done when:** `scripts/verify.sh` is still 13 ok, and the new wave 6 script
passes.

---

## Wave 5. Superset roles

Today both accounts land as `Gamma`, which cannot run SQL Lab (good) but does
hold `can_write` on Chart and Dashboard, so any user can edit or delete the
shared dashboards. The platform `admin` is also only `Gamma`, so the person who
should administer them cannot.

**Test first** (`apps/results-dashboard/tests/test_roles.py`): the config maps
Keycloak `admin` to FAB `Admin` and everything else to `AiscViewer`; the
`AiscViewer` definition holds no `can_write`, no `can_sqllab`, no
`can_execute_sql_query`; `AUTH_USER_REGISTRATION_ROLE` is `AiscViewer`, not
`Gamma`.

**Then build:** `AUTH_ROLES_MAPPING` plus an `AiscViewer` role created in the
existing `FLASK_APP_MUTATOR`, and `AUTH_ROLES_SYNC_AT_LOGIN = True` so a role
change in Keycloak takes effect at the next sign-in.

**Done when:** signing in as `user` lands in `AiscViewer` and the dashboard edit
controls are gone; signing in as `admin` lands in `Admin`.

---

## Wave 6. Proof

`scripts/verify-rbac.sh`, run against the live stack with two real sessions
(`admin` and `user`), asserting in both directions: what each may do and what
each must be refused. Same house style as `verify-sso.sh`, status code first,
then body. Wire it into `scripts/verify.sh` so it runs with everything else.

Assertions, roughly thirty: catalogue write refused for `user` and accepted for
`admin`; devpi upload refused; plugin install refused; audit log refused; a
project created by `admin` invisible to `user` until added; `user` added as
viewer can read every module and write in none; promoted to editor can write;
Superset role per account.

**Done when:** `scripts/verify.sh` reports one more suite, all green.

---

## Order and effort

Wave 1 first and on its own: it is the only item that is a code-execution path,
and it does not depend on anything else. Waves 2 and 3 are the foundation and
are where most of the thinking is. Wave 4 is mechanical once 3 exists. Waves 5
and 6 can be done in either order.

Rough sizes: 1 small, 2 small, 3 medium, 4 medium, 5 small, 6 small.

## Decisions worth confirming before wave 3

* Backfilling every existing account as owner of every existing project, rather
  than admin-only. Safe for this install, wrong for a hosted one.
* A non-member gets 404 rather than 403, so project names do not leak.
* Per-project roles as data rather than Keycloak groups. Groups would work but
  put project structure in the identity provider, where the modules cannot see
  it without another round trip.
