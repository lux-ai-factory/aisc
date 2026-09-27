# WP1 notes: control-objectives API auth (2026-09-25)

Scope: `apps/control-objectives` only (submodule, branch feat/unified-modules). Findings addressed from
01-inventory.md: 1 (JSON API open), 2 (root-path prefix bypass), 5 (id-addressed pages do not check
the object's project), 9b ("Start assessment" forwards only Authorization). Nothing pushed, nothing
deployed, the top-level submodule pointer is not bumped.

Commit (submodule): `9319256` "API auth WP1: every route but the public catalogue needs a verified
caller, an assessment is decided by its own project, and the gate reads the router's path".

## What changed

- `access.py`, `ProjectAccess` middleware:
  - Deny by default. Every request needs a verified caller (`aisc_identity.service.caller_from_headers`,
    so Bearer or `X-Auth-Request-Access-Token`) except the public list, matched as whole paths:
    `/health`, `/objectives`, `/api/config`, `/api/macro-requirements`,
    `/api/control-objectives`, `/api/control-objectives/{id}`, `/static/{name}`. No token is 401,
    auth misconfigured is 500 (as before).
  - It matches on `starlette._utils.get_route_path(scope)`, the function Starlette's router itself
    uses: the server's once-decoded path with the app's `root_path` removed. So the gate and the router
    always read the same string. This closes `/control-objectives/p/...`.
  - The project segment is no longer URL-decoded a second time (the old `unquote` let `/p/%2561bc`
    be checked as `abc` while the handler got `%61bc`).
  - A path under `/p/` from which no project can be read (`/p`, `/p//...`) is 404.
  - The verified caller is left on `request.state.caller` for the handlers.
  - New helpers `project_pid(engine, ref)` (slug or pid to pid) and `REFUSALS` (one wording per
    verdict).
- `api/app.py`:
  - `_view_of(request, id)` for the JSON API: loads the assessment, then `decide(method,
    access_for(engine, record.project, caller))`. Unknown id and stranger give the same 404 body
    (`Unknown project {id}`), viewer writing gets 403, editor/owner/admin allowed, DB down 503.
  - `GET /api/projects?project=` decides on the named project (pid or slug) the same way.
  - `_view_in(project, id)` for the pages: 404 unless the assessment's own `record.project` equals the
    path's `{project}`, directly (pid) or after resolving a slug with `project_pid`.
  - "Start assessment" takes the token with `token_from_headers` (Authorization Bearer, else the
    gateway header) and passes `Bearer <token>` on.
- `upstream.py`: `_headers` sends the caller's token both as `Authorization: Bearer` and as
  `X-Auth-Request-Access-Token` (constant imported from `aisc_identity.headers`). Both the platform
  (aisc_identity) and qualification-web (`tokenFromHeaders`) read either.

Decisions taken without the user (recorded here):
- `/`, `/docs`, `/openapi.json` are not on the RULES.md public list, so they now need a token. Behind
  Caddy every browser has one, so the launcher redirect and the docs still work for signed-in users.
- Without an `engine` `create_app` still runs ungated. The domain tests build it that way (about 20
  files); rewriting them is out of proportion. Instead a new test pins that `server.build_app` always
  passes the engine, which is the only production composition root.
- Object-level checks live in the handlers (they have the loaded record); caller and path-project
  checks live in the middleware, so a new route is still covered by the caller check by default.
- The upstream call sends both headers rather than choosing one, so neither callee depends on which
  one it reads first.
- `get_route_path` is a private Starlette helper (1.6.0 here). Importing it fails loudly if it ever
  moves, which is preferable to a hand copy drifting from the router.

## Route table, before and after

Auth = verified caller required; Authz = what decides membership.

| Method | Path | Before | After |
|---|---|---|---|
| GET | /health | open | open |
| GET | /objectives, /api/config, /api/control-objectives[/{id}], /api/macro-requirements, /static/{name} | open | open |
| GET | / (redirect), /docs, /openapi.json | open | Auth (401 without token) |
| GET | /api/projects?project= | **open** | Auth; member (viewer+) of `?project`; else 404 |
| GET | /api/projects/{id} | **open** | Auth; viewer+ of the assessment's own project; else 404 |
| POST | /api/projects/{id}/map, /severity | **open** | Auth; editor/owner/admin of its own project; viewer 403; stranger or unknown 404 |
| DELETE | /api/projects/{id} | **open** | same as above |
| GET | /p/{project}, /objectives, /projects | Auth + member, bypassable via `/control-objectives/p/...` | Auth + member of {project}, not bypassable |
| POST | /p/{project}/projects (start) | editor, bypassable; forwarded only Authorization | editor; forwards Bearer and X-Auth-Request-Access-Token |
| GET | /p/{project}/projects/{id} | member of {project}, object's project not checked, bypassable | member of {project} AND assessment of {project} (pid or slug), else 404 |
| POST | /p/{project}/projects/{id}/map, /severity | editor of {project}, object's project not checked, bypassable | editor of {project} AND assessment of {project}, else 404 |
| any | anything else (unknown routes, `/p`, `//p/...`, doubled prefixes) | open (404 from router) | Auth (401), then 404 |

## Tests

Throwaway Postgres per RULES.md (container `aisc-t-wp1-7f75737e`, 127.0.0.1:41019, init files
platform-db, project-databases, inspector-role, report-roles), removed afterwards.

| Run | Result |
|---|---|
| full suite at HEAD before any change (`351f41c`) | 297 passed, 1 skipped |
| new `tests/test_api_auth.py` against unchanged HEAD code (clean worktree) | **13 failed**, 8 passed |
| new `tests/test_api_auth.py` after the change | 21 passed |
| full suite after the change (`9319256`) | **318 passed, 1 skipped** |

The 8 that passed before are the positive cases the open API already satisfied (public paths open,
a viewer reads, the gateway header is accepted). Risk-mapper, per-project LLM keys and BAF tests
(`test_risk_mapping`, `test_project_llm`, `test_baf_llm`, `test_llm`) are unchanged and green.

One existing test changed, because the approved design changes the behaviour it pinned:
`tests/test_project_access.py::test_decodes_what_the_url_encoded` asserted the second decode
(`"/p/a%20b/x" -> "a b"`); it is now `test_does_not_decode_a_second_time` (`"/p/a%20b/x" -> "a%20b"`).

Bypass variants proven in `test_api_auth.py` (both with no token, all 401, and with a stranger's
valid token, all 404 or the router's own slash redirect to a gated path, never the data), on an app
built with `root_path=/control-objectives` as deployed: `/control-objectives/p/...`,
`/control-objectives/control-objectives/...`, trailing slash on `/p/.../projects/` and on an
assessment, `/%70/...` (encoded `p`), `/control%2Dobjectives/p/...`, `/p%2F{pid}/...`,
`/p/{pid}%2Fprojects/...`, `//p/...`, `/control-objectives//p/...`, `/api/projects/{id}/`,
`/control-objectives/api/projects/{id}`, doubled prefix on `/api`, `/api/projects%2F{id}`,
`/api//projects/{id}`. The double-decode case (`/p/%2530...`) is driven with a raw ASGI scope,
because TestClient decodes a path twice and cannot reproduce what uvicorn sends.

Command (from `apps/control-objectives`):
`CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test uv run --extra dev pytest -q -p no:cacheprovider`

## Live probes for the orchestrator, after deploying

GET only, on purpose: if the new image were not the one running, a no-token POST or DELETE would
act on live data (the old code has no gate on `/api/*`).

```
# the MCAS pid, read-only
PID=$(docker exec postgres psql -U aisc-postgres-user -d platform -tAc \
  "SELECT project_id FROM control_objectives.project WHERE id = '0a013fbcc79b'")
AID=0a013fbcc79b

# 1. no token, from the container that runs plugin code: every line must be 401
docker exec -e PID=$PID -e AID=$AID aisc-eval-worker sh -c '
B=http://control-objectives:8090; R=/control-objectives
for p in "/" "/docs" "/openapi.json" \
  "/api/projects?project=$PID" "/api/projects/$AID" "$R/api/projects/$AID" "$R$R/api/projects/$AID" \
  "/api/projects/$AID/" "/p/$PID" "/p/$PID/projects" "/p/$PID/projects/$AID" \
  "$R/p/$PID/projects" "$R/p/$PID/projects/$AID" "$R$R/p/$PID/projects/$AID" \
  "/p/$PID/projects/" "$R/p/$PID/projects/$AID/" "/%70/$PID/projects/$AID" \
  "/control%2Dobjectives/p/$PID/projects/$AID" "/p%2F$PID/projects/$AID" "//p/$PID/projects/$AID"; do
  printf "%s %s\n" "$(curl -s -o /dev/null -w "%{http_code}" --path-as-is "$B$p")" "$p"; done'

# 2. no token, public paths: every line must be 200
docker exec aisc-eval-worker sh -c '
B=http://control-objectives:8090
for p in /health /objectives /api/config /api/control-objectives /api/control-objectives/R1.1 \
  /api/macro-requirements /static/laif-logo.svg /control-objectives/objectives; do
  printf "%s %s\n" "$(curl -s -o /dev/null -w "%{http_code}" "$B$p")" "$p"; done'

# 3. no data leaks in any body (must print nothing)
docker exec -e PID=$PID -e AID=$AID aisc-eval-worker sh -c '
curl -s "http://control-objectives:8090/api/projects/$AID"; \
curl -s "http://control-objectives:8090/control-objectives/p/$PID/projects/$AID"' | grep -i "risk"
```

Then, in a browser signed in as a member (editor) of MCAS through the gateway
(`http://<host>/control-objectives/p/<slug-or-pid>/projects`): the list and an assessment open (200).
"Start assessment" is the end-to-end check of the token forwarding (it should open the existing
assessment of the latest version with a 303, not answer 502 "The platform did not answer ... 401"),
but it is a POST that can create an assessment when the latest version has none, so it is for the
user to click, not for a probe script. Optional with a realm token `$T` of a user who is NOT a member
of MCAS: `curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $T"
http://control-objectives:8090/api/projects/$AID` from eval-worker must be 404.

## Left open

1. Pre-existing, not introduced here: `/p/{slug}` and `/p/{slug}/projects` answer 500 when the page is
   opened with the slug, because `projects.list(slug)` compares the uuid column `project_id` with the
   slug. Same for `POST /p/{slug}/projects` (it stores the slug as the assessment's project). The
   launcher opens pages by pid, so this is latent. The fix is to resolve the path's project to its
   pid once (for example in the middleware, with `project_pid`) and hand the handlers the pid. Not
   done: it changes what every page handler receives and is outside WP1's list.
2. `create_app(engine=None)` is ungated by design for the domain tests; only `server.build_app` is
   pinned to pass an engine. A second composition root would need the same care.
3. `/api/config` stays public per RULES.md and still discloses provider and model (`ollama`,
   `mistral:latest`), as noted in the inventory.
4. The submodule pointer in the top-level repo is not bumped (orchestrator's job), and nothing is
   deployed; the probes above are for after the image is rebuilt.
