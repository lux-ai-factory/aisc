# Changelog of the aisc root repository (newest first).

## Unreleased: connections without the key on resolve, params, tools, run keys that end with their pass

### Changes
- The internal resolve routes answer a connection's descriptor without its key (`has_secret` says whether it has
  one), under a run pass and under the connections token alike; only the protocol doors and the Test button
  decrypt it. Resolve and run-key issuance no longer need `PLATFORM_SECRETS_KEY`.
- `aisc/ask` takes `params` (a template's `{{params.x}}`, or an OpenAI-compatible model's settings) and full
  OpenAI-style histories (tool calls, tool results). A request the platform will not send is a 400 with the
  reason; a failed call is a 502 `{error, status, detail}` with every key scrubbed. Bodies over 2 MiB are 413.
- A run key issued under a run's pass ends with it: deleted when the worker revokes the pass, refused once the
  pass is gone, and never valid past the pass's expiry. Project migration `0022_run_key_pass.sql`.
- The protocol doors cap calls per run (`PLATFORM_FACADE_RUN_CAP`, default 8) as well as across the platform
  (`PLATFORM_FACADE_THREADS`, now 32 by default). A call over a cap waits.
- Credentials in custom headers (`secret_headers`): stored encrypted, sent with every call, masked as `***` on
  resolve, scrubbed from errors, rotated with the key. A plain header whose name looks like a credential is
  refused at save. Project migration `0023_connection_secret_headers.sql`; Manage, Connections, Advanced lists
  them by name with a remove box.
- An OpenAI-compatible connection can say it carries tools and log probabilities (`supports_tools`,
  `supports_logprobs`; project migration `0024_connection_capabilities.sql`). The run key advertises `tools`
  then, `aisc/ask` and the OpenAI door carry tools and tool results to it and its tool calls back, and the Test
  button checks each flag with one more call (`capability_missing` when one fails).
  Check: `scripts/test-platform.sh tests/test_facade_tools.py`.
- A system that echoes its credentials never hands them back: every protocol door scrubs the key and each secret
  header value (as they are, base64 or URL-encoded) from a 200 answer's output, refusal reason and tool calls,
  and a secret header value is taken out of an error before the 300-character cut. The integrator's trial
  gateway uses the same `scrub_answer`. Check: `scripts/test-platform.sh tests/test_answer_scrubbing.py`.
- Connection, header, parameter and tool names are checked whole: one with a trailing newline is refused (422 at
  save, 400 at the doors), never stored or a 500. Check: `scripts/test-platform.sh tests/test_exact_names.py`.
- The allowlist keeps each name's lookup for `PLATFORM_ALLOWLIST_CACHE_S` seconds (default 30, 0 turns it off),
  so a door call no longer resolves every service name of the stack. Check:
  `scripts/test-platform.sh tests/test_allowlist_cache.py`.

## 2026-10-23: plugins are fetched on install

### Changes
- `start` no longer clones any plugin. The `plugin-downloader` service and `docker-compose.plugin_downloader.yml`
  are gone, and `def_plugins/` is not used by `start` (it can be deleted by hand; the engine-standalone compose
  still mounts it). `plugin-publisher` is now a service that stays up: it puts the shared plugin interface on
  the package index at its start, and publishes one plugin when an admin installs a test from the catalogue
  (the platform asks it, with `PLUGIN_PUBLISHER_TOKEN`). The first install of a test takes about a minute and
  needs GitHub reachable from the stack. Check: install a test from a project's catalogue.
- `GITHUB_TOKEN`, for the private plugin repos, now goes to `plugin-publisher` only.
- An install that failed to fetch says "could not fetch <repo>: ...; nothing was installed".
- `start` removes the exited `plugin-downloader` container an older install left, so compose stops warning
  about an orphan. Check: `scripts/tests/test_start_script.py`.
- `scripts/verify-plugins.sh` checks the publisher and the interface instead of reading the downloader's
  logs, and `--install <slug>` installs one catalogue entry end to end.
- The package index is kept between starts (the `devpi_data` volume); the guide said otherwise.

## 2026-10-21: AISC starts whatever ports are taken

### Changes
- The README takes a first-time installer from nothing to a running AISC: Docker and uv are installed per
  system (Windows, macOS, Linux), then everyone downloads and starts AISC with the same commands. Check:
  `scripts/tests/test_readme.py`.
- The add-controls service and its private submodule are removed, so every submodule is public and the clone
  needs no GitHub account. To bring it back: `git revert b3b069e`.
- `uv run scripts/aisc.py start` checks every port before it builds anything. When a browser port (80, 8100,
  8188 or 8081) is taken, an install not served over https moves to a free one, says so, and keeps the choice
  in `env.local`; an https install stops and names the port. Check: run `start` with one of them held.
- Only the browser ports are published by default. PostgreSQL, Redis, RabbitMQ, MinIO and immudb are published
  on `127.0.0.1` only with `AISC_ADMIN_PORTS=on` (in the environment or `env.local`), and 443 only on an
  install served over https. Check: `docker compose -p aisc ps` shows no 5432 without the setting.
- `start` tells the sign-in the install's addresses on every start, so a port that moved is the address people
  return to after signing in.
- `start` names the sign-in that works on the install, and waits for the realm page to answer before it says
  "AISC is up". On Windows it finds Docker on the PATH. It reads `env.local` as a person may edit it (quoted
  values, notes and settings of their own are kept). It removes the containers a failed attempt half-made.
  Every long-running service has a restart policy, so AISC comes back by itself once the Docker daemon runs
  again (Docker Desktop must itself start at sign-in; if it does not, start it). The engine's audit clerk logs
  in to immudb again by itself when its login ended, so no manual restart of `aisc-backend` is needed.
- The checks (`verify-*.sh`) reach the install's real addresses, whichever port moved.
- Step 3, the catalogue, follows a moved engine: it reads the engine's address from the launcher's
  `/origins.json`, so its Back link, project and control install work without a rebuild. Check: open the
  catalogue from a project on an install whose engine is on 8080.
- Lint cleanup, with no change in behaviour.

How to check: `uv run scripts/aisc.py start`; the tests named in each commit (`git log --oneline c504aac..HEAD`);
and the full check `scripts/verify.sh --port-fallback`, which lands in the next commit.

## 2026-10-18: the engine is ours to change

### Changes
- The engine (apps/backend, apps/eval) is no longer held to its upstream: `scripts/guard-frozen.sh` retires G1
  and G5 and G4 checks only the webapp. The changes once proposed for its maintainers are made, so
  `docs/engine-proposals.md` is gone:
  - the engine admits callers with `aisc_identity.access`, as every other service does;
  - it accepts only tokens issued to the gateway (`ENGINE_ACCEPTED_CLIENTS`);
  - plugins run as an unprivileged user that cannot read the worker's environment, and the worker runs with
    `no-new-privileges`;
  - its changes are recorded in the project's ledger: written to an outbox in the change's own transaction
    and sent by `aisc-backend-ledger`, the only engine process holding the engine's ledger token (the backend
    imports plugin code). The registry declares the new engine actions; their routes leave the exceptions.

## 2026-10-16: review fixes (root, platform, report-composer)

### Security
- report-composer refuses at save an SVG logo holding `<image>`, `<feImage>`, `href` or `xlink:href`: an
  embedded raster is decoded in full whatever size the SVG declares (composer side).
- report-composer takes only the dashed pid form as an id, as the platform and control-objectives do: a
  project slugged with 32 bare hex digits is found by its slug, never as another project's pid.

### Fixes
- report-composer refuses at save an SVG logo with no usable size (no width and height, nor a viewBox for the
  side it lacks), read as cairosvg reads it, since the renderer refuses it at every preview and generation;
  a lone surrogate in an imported layout file is 422 on `/file/...`, not 500.
- `scripts/start.sh` ends with a warning for every one-shot service that exited non-zero (plugin-publisher
  when a plugin did not build), with the command that shows why.
- The platform reads the dashboard's public address from `DASHBOARD_EXTERNAL_URL`, the name the launcher and
  the reports use; compose gives it to the platform. `DASHBOARD_PUBLIC_URL` is no longer read.
- platform: the protocol endpoints call systems under test in threads of their own
  (`PLATFORM_FACADE_THREADS`, 16; a call over the cap waits), so slow systems cannot take the threads every
  other request, Caddy's forward_auth included, needs. The setup retry pass (databases and
  dashboard registrations that failed) runs in a background thread, never in the request that starts it.
- platform: a person's event on the internal ledger route with no request id (the dashboard's, when the
  witness gave none) is queued and recorded by the relay as rejected (`missing_request`), so it shows in the
  Activity log; before, it was refused at the door and seen nowhere.
- The engine's immudb login lasts a year: immudb's `IMMUDB_TOKEN_EXPIRY_TIME` is 525600 minutes (its default,
  a day, made the engine's audit log answer 500 a day after every start), and `aisc-backend` restarts when
  compose restarts immudb, whose restart ends every token (`depends_on ... restart: true`).
  `verify-rbac.sh`'s audit check is still a FAIL when the log does not verify, and now names the likely cause
  and `docker compose -p aisc restart aisc-backend`. Still not covered: immudb restarted outside
  compose (`docker restart immudb`, or Docker after its daemon restarts) leaves the engine's audit writes
  failing until aisc-backend restarts. The full fix, the clerk logging in again, is in the frozen engine
  code (`aisc_backend/audit/clerk.py`), for the engine's maintainers. Trade-off: a login token stays valid a year unless immudb
  restarts.
- Tests: the seven removal-lock and source-grep tests of `scripts/tests/test_stale_code.py` are retired; the
  logs page's filter loop is now run in node (`test_logs_page_filters.py`).
- This changelog: two known reds an earlier pass had fixed are dropped, and the 2026-10-14 logo entry no longer
  overclaims.

### Deploy
- Rebuild aisc-platform and report-composer; recreate immudb and aisc-backend (`up -d`) for the token
  lifetime and the restart link. Nothing here is live until then.

## 2026-10-15: one access model for immudb

### Security
- Only `immudb` and `ledger-pool` hold immudb's superuser password (`IMMUDB_ADMIN_PASSWORD`). The engine, its
  migration and the dashboard no longer get it.
- The engine writes its audit log as its own immudb user `aisc_engine` (read on `defaultdb`, read-write on
  `auditdb`, SQL SELECT/CREATE/INSERT only), password `ENGINE_IMMUDB_PASSWORD`; `ledger-pool` makes the
  account. Its events stay outside the platform ledger.
- The results dashboard has no immudb path any more: Superset keeps its actions in its own action log, and
  comments and reviews reach the ledger through the platform.

### Behaviour
- `aisc-backend` starts only after `ledger-pool` completed successfully (fails closed).
- `scripts/secrets.sh` generates `ENGINE_IMMUDB_PASSWORD` (kept by `--rotate`) and gains `--rotate-one NAME`
  for `IMMUDB_ADMIN_PASSWORD`, `LEDGER_IMMUDB_PASSWORD` and `ENGINE_IMMUDB_PASSWORD`; `ledger-pool` brings
  `aisc_ledger` and `aisc_engine` to the configured passwords at its next run.
- `ledger-pool` grants a database only when the user lacks it: a re-grant ended the platform's open immudb
  sessions at every start.
- New `scripts/verify-immudb.sh` (read only); `scripts/verify-rbac.sh` checks that the admin's engine audit
  log answers 200 with `"verified": true`.

### Deploy
- Rebuild aisc-platform and aisc-results-dashboard, run `scripts/secrets.sh`, then a full `up -d`.

## 2026-10-14: review pass (branches pass/root-infra-2026-10-13, pass/platform-2026-10-13, pass/composer-2026-10-13)

Areas: root infrastructure (compose, Caddyfile, scripts, launcher pages, dashboard-gateway, env files),
`platform/`, `apps/report-composer/`. Nothing here is live until the stack is rebuilt and restarted with
`./scripts/start.sh` (which also runs `scripts/secrets.sh`).

### Security
- Superset's cache moves to its own password-protected Redis, `dashboard-redis` (`DASHBOARD_REDIS_PASSWORD`),
  on a network the eval worker cannot reach. Stack: `docker compose -p aisc ps dashboard-redis` is up, publishes nothing.
- `POSTGRES_PASSWORD`, `S3_PASSWORD`, `RABBITMQ_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD` are generated by `secrets.sh`
  and kept by `--rotate`; an existing install keeps the values it runs on. Keycloak publishes 8081 on 127.0.0.1 only.
  Stack: `ss -tln | grep 8081` shows `127.0.0.1:8081`.
- Flower (`/flower/`) asks the admin gate after sign-in: a non-admin gets 403. Its link is admin-only in Manage.
- The schema-diagram server and the platform's schema gate judge the decoded path: `%2e%2e` and other
  escaped climbs answer 404, no folder is listed.
- The standalone engine compose publishes 8000 and 8080 on 127.0.0.1 only.
- dashboard-gateway accepts only tokens issued to the gateway's client (`azp`, `AISC_GATEWAY_CLIENT_ID`); takes
  effect when the dashboard is recreated.
- qualification-web and controls-web get `AUTH_ENABLED`, `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URL` to verify the
  gateway's token; report-composer cites `X-AISC-Request-Id` only with a valid gateway token.
- The engine checks TLS when it lists a provider's models (`MODEL_LISTING_SSL_VERIFY=True`).
- report-composer: a metric name can no longer break out of the block form's attribute (stored XSS).
- platform refuses a slug shaped like a project id (422); report-composer looks an id-shaped reference up only as a pid.
- report-composer refuses at save a raster logo the renderer would refuse (over 16,000,000 pixels, unreadable
  size) and an SVG logo that declares a size too large: 422 `invalid_template` on `/logo/data_base64`. (An SVG
  with no usable size was still taken, though the renderer refuses it; fixed on 2026-10-16, see above.)

### Fixes
- Scripts: `verify-db-access.sh` deletes only its own probe project and logs in as `report_composer_rw` /
  `report_ro` with their generated passwords; it, `verify-rbac.sh` and `verify-sso.sh` FAIL when their probe
  fails instead of passing; `verify-plugins.sh` P3 installs the newest version (PEP 440 order);
  `verify.sh --superset-upgrade` checks the stack's own Superset image by default; guard G4 requires
  plugin-interface exactly at its pin and clean; `secrets.sh --rotate` keeps `DEVPI_ROOT_PASSWORD` and
  `SUPERSET_SECRET_KEY`; `Throwaway.scalar()` raises on a failing query.
- Compose: `plugin-publisher` uploads what built and exits 1 naming the plugins that did not;
  `report-grants` waits for `dashboard-migrate`.
- Launcher: links take the install's addresses from `/origins.json` (`API_URL_EXTERNAL`,
  `KEYCLOAK_URL_EXTERNAL`, `DASHBOARD_EXTERNAL_URL`); a refused project list shows the status, not
  "No projects yet". Stack: `curl -s http://localhost:8100/origins.json`.
- Dead code and contrary comments removed (`scripts/verify-catalogue-mapping.sh`, `REPORT_GRANTS_WAIT_SECONDS`,
  a doubled oauth2-proxy flag, host-network comments); dashboard-gateway's tests run in the root suite and in
  `verify.sh --modules`.
- platform: protocol endpoints call the system under test in the thread pool (one slow system no longer stalls
  every request); provisioning and dashboard retries run outside the setup lock; removing every evidence link is
  recorded; the Activity log waits for the relay at most 5 s, then 503, instead of a false index alarm; a tamper
  alarm on the events list and head is 409, another ledger error 503; the internal connection guard runs once;
  reviving a connection whose target is taken names the holder (409); `dashboard-redis` is on the connections
  deny list; the `controls.submission.answers_removed` ledger action is registered.
- report-composer: a renderer refusal at generation is 422 `invalid_snapshot`; the renderer's 413 and busy 503
  reach the person as `report_too_large` / `renderer_busy`; a non-JSON renderer answer is 502; a built-in's
  record is written with its ledger events; races with a delete answer 404 / 422, not 500; a lone surrogate or a
  period ending 9999-12-31 is 422; imported names stay unique at 120 characters; Create layout posts without a
  redirect; every database connect gives up after 10 s.
- Tests: duplicate, removal-lock and text-grep tests retired across the three suites.

### How to check
- Root: `uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider scripts/tests`
  (known red: `test_ledger_coverage.py::test_every_state_changing_route_has_its_event`).
- Platform: `scripts/test-platform.sh -q` (the 4 TypeScript-twin tests need `apps/qualification` and `apps/controls`).
- Report composer: `cd apps/report-composer && uv run --extra dev pytest -q`.
- Running stack, after the restart: `./scripts/verify.sh --stack` (known red: one `verify-sso.sh` check of the
  catalogue's compose defaults, which belong to the engine's maintainers).
