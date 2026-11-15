# Changelog of the aisc root repository (newest first).

## Unreleased: connections without the key on resolve, params, tools, run keys that end with their pass; hardening after the audit of every change since 31 October

### Upgrading an existing install
- Append-only results and kept settings. The engine's migration `0029_append_only_results` makes measures and
  observations append-only (never changed, removed or truncated, not even by the owner), writes the ledger outbox
  only through `engine.ledger_outbox_append`, `engine.ledger_outbox_mark` (a delivery mark is set once) and
  `engine.ledger_outbox_mask`, and lets a saved plugin configuration change only by masking a secret in it (its
  name and description stay editable; it is never removed). `0030_settings_are_kept` marks a deleted project
  setting deleted instead of removing it: the configurations that used it keep their link, and its key may be
  given again. A setting's update records the value it had and the value it takes in the ledger (`before`,
  `after`), its deletion the value it had; a secret's events still name only its key. The new guards are listed in
  `init/guard-triggers.txt`, and `scripts/verify.sh --stack` runs `scripts/verify-guard-triggers.sh`, which reports
  a guard trigger that is missing, disabled, or on a table its owner role no longer holds. Ledger copies of a
  plugin configuration now hide what the plugin's form marks and what the stored rule takes for a secret, never a
  value for its name alone (`tokens: 512` stays readable). The canonical JSON of the ledger lives in
  `aisc_identity.canonical` (the vendored wheels of the backend and the eval worker carry it). Back up first
  (`scripts/backup-databases.sh`), restart postgres-setup (the guard list), then rebuild and recreate the platform,
  aisc-backend, its one-shot and the ledger sender.
- Module owner roles. Each module now migrates its project databases as its migrator, acting as its owner role:
  `PROJECT_MIGRATE_DATABASE_URL` for qualification and controls (their one-shots and web apps) and for control
  objectives, `REPORT_COMPOSER_PROJECT_MIGRATE_DATABASE_URL` for the report composer, `DB_MIGRATE_USER` and
  `DB_MIGRATE_PASSWORD` for the engine (aisc-backend, its one-shot and the ledger sender); compose builds them
  from the `*_MIGRATOR_PASSWORD` values of `scripts/secrets.sh`. At the first start each module's new migration
  hands the tables its runtime role made to its owner role (`REASSIGN OWNED`), takes `CREATE` on the schema from
  the runtime role and leaves it `SELECT`, `INSERT`, `UPDATE` and `DELETE` (only `INSERT` and `SELECT` on the card
  history, the form versions, the mapping archive and the layout revisions). References to a card version restrict
  its deletion in every module; an AI card is never deleted; a run's card version is fixed when it starts. The
  guards that keep an AI card, its history, the mapping archive, the layout revisions and a run's card version are
  listed in `init/guard-triggers.txt`, so not even a migration lifts them. A module migrates a project database
  only once its schema is its owner role's: while the platform has not handed it over yet, the one-shot waits
  and tries again. Back up first (`scripts/backup-databases.sh`), restart postgres-setup, start the platform, then
  rebuild and recreate every module.
- Owner roles. Run `scripts/secrets.sh` first: it adds the six `*_MIGRATOR_PASSWORD` values, which
  postgres-setup applies and `PLATFORM_MIGRATE_DATABASE_URL` uses (the platform refuses to start without it).
  postgres-setup now makes NOLOGIN owner roles (`<module>_owner`) and their migrator logins
  (`init/owner-roles.sql`), takes `CREATEDB` and `pg_signal_backend` from `platform_rw`, and installs
  `init/project-database-setup.sql` in `template1` and every project database (the functions that hand a module
  schema to its owner and end a project's sessions, and the alarm that refuses disabling or dropping a listed
  guard trigger, `init/guard-triggers.txt`). At its next start the platform migrates as `platform_migrator`:
  its own tables, the project databases and the platform's schemas in them pass from `platform_rw` to
  `platform_owner`, and each module schema to its module's owner role; `platform_rw` keeps reading and writing
  rows, nothing more (no `DELETE` on card versions, insert and read only on the run trace and the verified
  ledger state). Card versions refuse `DELETE` and `TRUNCATE` for everyone (a card is corrected through a
  revision; a project leaves by dropping its database), and evidence restricts instead of cascading. The
  verified ledger state becomes a log that only grows (`ledger.state_log`; `ledger.state` is copied once and
  kept read-only). The database inspector reads by schema, never a project's `connection`, `llm` or `helper`;
  nobody connects to the platform database through `PUBLIC`. Back up first (`scripts/backup-databases.sh`), then
  restart postgres-setup and rebuild and recreate the platform; the modules keep their roles until their own
  migrations move to their owners.
- Addresses are checked at the call. Loopback and the unspecified address (`0.0.0.0`, `::`, mapped forms) are
  reached only by hosts in `CONNECTIONS_ALLOWED_HOSTS` (and, for model addresses, the host of
  `PLATFORM_OLLAMA_BASE_URL`), even when a project allows the name; every address that is not globally routable
  (also CGNAT `100.64.0.0/10`, benchmarking, protocol assignments) needs an entry under Manage, Connections. A
  self-hosted model server (provider connection) is refused at save when the rule refuses it; model listings, a
  helper's endpoint at run start (the run fails naming why) and an agent's project model are checked before any
  request. A model server on a private address (a LAN GPU box) needs an allowed-host entry in each project that
  uses it. Rebuild and recreate the platform, the eval worker, the engine, control-objectives and the
  qualification agents; restart the plugin publisher so devpi takes the rebuilt interface.
- Boundaries are strict. The engine refuses a component file that is empty (422), larger than
  `TARGET_FILE_MAX_MB` (2048 by default, now given to the engine as well as the platform; 413) or not of its type
  (415: a dataset takes `.csv .tsv .parquet .json .jsonl .zip`, a model `.onnx .pkl .joblib .pt .pth .safetensors
  .h5 .keras .zip`), and a plugin artifact above the same cap; the platform passes these refusals on instead of a
  502. A run's artifact list previews only the first 256 KB of a file (a png, pdf or zip larger than that shows
  no preview: download it). Project, member and AI system bodies refuse unknown fields and overlong text (an AI
  card description is at most 2000 characters). `POST /api/v1/audit` on the engine takes `X-AISC-Project` and an
  editor of that project, names the app from the token's client, and refuses `source_app` or any other unknown
  field in the body. Rebuild and recreate the engine, the platform and the qualification prefill service.
- `AUTH_ENABLED` and `LEDGER_MODE` are read strictly by every service: on words `1 true yes on`, off words
  `0 false no off`, ledger modes `off record enforce`, case and surrounding spaces ignored. Any other value, an
  empty one included, stops the service at start with a message naming the variable, where it used to mean off.
  An absent `LEDGER_MODE` now means `record` (the stack already sets `record`); a standalone engine still records
  nothing. The platform writes a `ledger.mode` event to its own log at every start, off included. After the
  restart, `scripts/verify-switches.sh` (also run by `verify.sh --stack`) checks the switches, the latest
  `ledger.mode`, that Redis answers `NOAUTH` and that no log holds a token-shaped string.
- Backups: `bash scripts/backup-databases.sh` backs up every database, the immudb ledger and its key, MinIO's
  files and the secrets file (encrypted), and restores each into a throwaway to compare it
  (`docs/runbooks/restore-a-backup.md`). Make its passphrase file first. `bash scripts/schedule.sh --install` runs
  it daily at 02:30 and `scripts/verify.sh --stack` at 03:30; nothing is scheduled until you run that.
  `aisc.py remove` offers a backup before it deletes the volumes.
- `secrets` and `start` refuse an empty `PLATFORM_SECRETS_KEY`, `DJANGO_SECRET_KEY`, `ENGINE_SECRETS_KEY` or
  `PLATFORM_LEDGER_KEYS` line instead of making a new key: put the old value back (from `env.runtime` or the
  backup's secrets copy).
- New secret `ENGINE_SECRETS_KEY`: the engine encrypts the credentials it stores with this key of its own, no
  longer with one derived from `DJANGO_SECRET_KEY`. `uv run scripts/aisc.py start` adds it; the backend and the
  eval worker take it when they are recreated, and the backend refuses to start without it. Values stored before
  still decrypt, so `DJANGO_SECRET_KEY` stays kept by `secrets --rotate` until they are encrypted again.
- New secret `REDIS_PASSWORD`: the shared Redis (the worker's Celery results) asks for it. `uv run scripts/aisc.py
  start` adds it without changing any other secret; the redis, backend, eval worker and flower containers take it
  when they are recreated. Results of tasks in flight at that restart are lost, so restart with no run going.
- Flower (the eval queue monitor) no longer starts with the stack: it read every project's task arguments on the
  internal network without a login. Start it when needed with `COMPOSE_PROFILES=inspect ./scripts/start.sh`.
- Sign-in lockout is on: five wrong passwords lock an account for 60 s, growing to at most 15 minutes. Start
  applies the realm's lockout settings to an existing realm too.
- The `platform` database no longer gives CONNECT and TEMPORARY to every role (PUBLIC); each module role keeps
  its own. Applied by the database setup step at the next start.
- The results dashboard creates two tables at start, `aisc_removed_chart` and `aisc_changed_chart`: plugin
  default charts removed or changed with the chart assistant stay so through a tile sync.
- `aisc.py drift` lists the running containers that no longer run what their image holds (read-only).
- Plugins on a plugin interface below 0.4.0 that call a connected target directly no longer reach it: the resolve
  route answers without the key. Every plugin must take interface 0.4.0.
- New secret `PLATFORM_ENGINE_TOKEN`: `uv run scripts/aisc.py start` adds it; a bare `docker compose up` fails
  until `uv run scripts/aisc.py secrets` is run.
- New secret `PLATFORM_CONTROLS_TOKEN` (the checklists app's proof files): added the same way. The platform now
  holds the stack's S3 settings and makes a MinIO bucket `proof-<pid>` per project; a project made before gets
  its bucket with its first proof file.
- Migrations applied at the next start: platform `0013_run_pass_use` and `0014_ledger_content_redaction`; every
  project database `0022_run_key_pass`, `0023_connection_secret_headers` and `0024_connection_capabilities`; the
  engine `0024_drop_stored_langbite_judge_keys`, which now changes nothing: the LangBiTe judge fields are removed
  by the cleanup (below). An install that already ran the earlier 0024 has lost those fields with no backup:
  rotate its LangBiTe judge keys.
- Plugin configuration keys: a save keeps each key as a project secret; a stored configuration with a key in
  clear cannot be restored (409); saving it again moves its key into a project secret; an adopted plugin refuses
  a key field (422).
- Run the cleanup dry run `scripts/clean-old-secrets.sh` (see `docs/runbooks/clean-old-secrets.md`), then rotate
  every key it lists, then run it with `--apply`. It also retires the LangBiTe `judge_api_key` and `judge_model`
  fields (the judge is a helper model now), listed as `retired` lines.
- Engine component names change from "Target · ..." to "AI card · ..." (renamed in place).
- The eval worker no longer passes `AISC_TARGET_API_KEY`, `OPENAI_API_KEY` or `API_KEY_OPENAI` from its own
  environment to plugins.
- A run pass names only the evaluation's own project; a component naming another project's target or connection
  is refused (400).
- The plugin publisher replaces a published version whose content changed; the vendored plugin-manager is
  `0.3.0+aisc.1`.
- The eval image carries Node 22.22.0 and promptfoo 0.125.1.
- StrongREJECT is released as `aisc-plugin-strongreject` 0.1.2 and LangBiTe as `aisc-plugin-langbite` 0.2.11:
  the versions where a failing target fails the run instead of scoring as safe. The engine and worker install a
  plugin by exact version, so an install that holds 0.1.1 or 0.2.10 keeps the old code: once the branch each
  catalogue entry names carries the new version, install StrongREJECT and LangBiTe again from the catalogue.
- Every project database gets `0028_target_file` at the next start (the uploaded file of a target).
- Every project database gets `0030_connectivity` at the next start: provider keys, agent choices and helper models
  move into connections (`connection.endpoint` kind `provider`, `connection.use`); see Manage > Connectivity.

### Changes
- Dashboard events (Save to report, the chart assistant's validate, change and remove) now name their dashboard,
  so the ledger accepts them; before, every one was rejected as belonging to no project.
- Save to report: editors and admins only, and only under the name of a chart placed on that dashboard.
- Chart assistant: it knows every plot by its definition, changes a matching plot in place (title, bar or line,
  axis range, percentages), removes a plot only when the request asks to delete, and asks which plot when two
  show the same thing; its query check no longer lets a WITH name hide a system table, and column names are
  quoted wherever a validated chart uses them.
- Connectivity: an owner may make only a provider connection a test tool, and sees each connection's name, kind
  and use; admins see everything. The helpers page no longer removes or rewrites a connection made a tool on
  Connectivity. Deleting a connection ends its uses.
- Platform: proof files are type-checked without unpacking a whole archive member; a call to the system under
  test is recorded even when it holds characters the database cannot store; a run's call trace still verifies
  after the database rewrites its numbers, and its digest is sealed in the ledger when the run's pass ends.
- One owner/admin rule table decides the connection, connectivity, helper and model routes.
- Engine: Stop saves every stopped test and the run with one ledger event citing the person's request; a stopped
  test stays stopped when the worker reports late; a plugin may not write files under the worker's own names.
- Reports: the Exported results block keeps two dashboards of the same title apart and says its plots are as
  saved; the "treated like the baseline" figure says how many runs it pools.
- `scripts/suites.py` is the one list of test suites; every folder with tests that compose builds has a row.
- The platform stops a run whose calls keep failing, for every plugin: after 3 failed calls in a row, or once more
  than 5% of at least 20 sent calls failed, the run's next calls are not sent, are recorded `not_sent`
  (`run_stopped`) and are refused with the reason (403). `PLATFORM_RUN_STOP_IN_A_ROW` (3),
  `PLATFORM_RUN_STOP_RATE` (0.05) and `PLATFORM_RUN_STOP_AFTER` (20) set it; 0 turns a rule off.
- Manage > Connectivity replaces AI assistant models and keys, Components and connections and Helper models in the
  menu: one connection model (provider connections, their uses by the Configurator's agents and as test tools),
  the assessed system kept apart by the database.
- A model or data component of the AI card can be reached by an uploaded file, under Manage > Components and
  connections (`PUT /projects/{slug}/targets/{key}/file`, up to `TARGET_FILE_MAX_MB`, 2048 by default): the
  platform makes one engine model or dataset component for it and the engine stores the bytes; the row shows the
  file's name, size and SHA-256. The engine's Settings panel, in the Configurator, is now **Test data**: it adds
  datasets and datashapes only and no longer lists what the platform makes from the AI card. The run form is
  unchanged.
- One version of a test's package is on in a project: installing a version, or switching one on, turns the
  package's other versions off (kept, with their settings and evaluations). The event of the install
  (`plugin.installed`) or of the switch (`engine.plugin.toggled`) names the versions turned off (`turned_off`); the
  engine lists the version on first and the run page shows only versions on.
- Step 4's test tiles: one tile per test of a package, matched by its name, so a test whose class was renamed
  between versions (LangBiTe Mijke 0.2.8 to 0.3.0) keeps one tile with the runs of every version; its Configure
  and Run open the version on.
- The documentation as one PDF: `scripts/docs_pdf.py` builds `build/AISC-documentation.pdf` from README.md and
  docs/ in the look of a Word template given to it (not kept in the repository): links between
  pages jump within it, links to other files go to GitHub, Mermaid diagrams become pictures. The Markdown stays
  the only source. Keycloak's lockout threshold in the realm file is 5 wrong passwords (was Keycloak's default
  of 30); lockout itself stays off.
- Proof files for checklist answers: the platform takes a file from the controls app
  (`POST /internal/projects/{pid}/proof-files`, its own token), reads its type from its bytes (PDF, Office,
  OpenDocument, CSV, text, PNG, JPEG, WebP; the extension must agree), refuses one over 25 MB, stores it under
  its own id with its SHA-256 in the project's bucket and never replaces or deletes it while the project
  exists. The bucket is made with the project's database and removed when the project is deleted. Ledger
  actions `control.proof.attached` and `control.proof.removed`.
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
  gateway uses the same `scrub_answer`. Error texts take the same forms (`secret_forms`): the doors' 502
  detail, warning logs, the Test button and its capability checks, `last_test_detail`, and the interface's
  scrub before the cut. Limits: hex, unpadded base64, double encodings, case changes and a secret split across
  output items or calls are not scrubbed; the target must not echo credentials, and the scrub is a safety net,
  not a guarantee. Check: `scripts/test-platform.sh tests/test_answer_scrubbing.py tests/test_encoded_secrets.py`.
- Connection, header, parameter and tool names are checked whole: one with a trailing newline is refused (422 at
  save, 400 at the doors), never stored or a 500. Check: `scripts/test-platform.sh tests/test_exact_names.py`.
- The allowlist keeps each name's lookup for `PLATFORM_ALLOWLIST_CACHE_S` seconds (default 30, 0 turns it off),
  so a door call no longer resolves every service name of the stack. Check:
  `scripts/test-platform.sh tests/test_allowlist_cache.py`.
- A run pass names only the evaluation's own project: the worker sends the run's platform project with every
  mint, and the platform refuses a reference of another project (403) or a mint without a project (422). The
  engine refuses a component whose value names another project's target or connection, or a malformed one (400).
  Check: `scripts/test-platform.sh tests/test_run_pass_own_project.py` and
  `scripts/lib/engine-tests.sh aisc_backend.tests.test_component_reference_project`.
- StrongREJECT and LangBiTe never record a failed or empty run as a score: the run fails with its reason (step,
  exception type and HTTP status only). StrongREJECT fails on any missing attack, whatever the share, and when the
  evaluator returns no score at all. Both fail when more than a tenth of the prompts or cases is unanswered (a
  failed call or an empty answer) or, for StrongREJECT, unanswered or unscored, and when none is answered;
  otherwise the answered ones are scored and an `Unanswered prompts` measure counts the rest. LangBiTe refuses a
  configuration that matches no prompt. No placeholder 0.0 measure is written any more. Check: each plugin's `tests/` (`test_failed_runs.py`).
- The plugin publisher builds on every publish and uploads when the version is missing from the index or its wheel
  content (members by hash) changed, for plugins and the interface alike; the answer says `replaced`. The vendored
  plugin-manager is `0.3.0+aisc.1`, upstream's 0.3.0 plus this checkout's commits. Check:
  `cd infra/plugin-publisher && uv run --with pytest pytest -q` and `scripts/tests/test_plugin_interface_pins.py`.
- The eval worker hands plugins none of its own model keys (`AISC_TARGET_API_KEY`, `OPENAI_API_KEY`,
  `API_KEY_OPENAI`); the model addresses still pass. Check: `apps/eval` `tests/test_plugin_environment.py`.
- The public evaluation routes (`GET /api/v1/evaluations/{pid}`, `GET /api/v1/projects/{pid}/evaluations`) answer
  each plugin's configuration masked; the worker's internal route keeps the stored one. Check:
  `scripts/lib/engine-tests.sh aisc_backend.tests.test_evaluation_config_masked`.
- Installing or refreshing a package whose plugin is configured answers 200 with the configuration masked (it
  failed with 500). Check: `scripts/lib/engine-tests.sh aisc_backend.tests.test_plugin_install_refresh_configured`.
- Saving over a stored configuration whose key is still in clear, with the key field left empty, keeps that key
  as a project secret instead of losing it. Check:
  `scripts/lib/engine-tests.sh aisc_backend.tests.test_old_key_kept_on_save`.
- The worker uploads a plugin's files without the values it handed the plugin (project secrets, the run pass,
  secret-named configuration values), replaced byte for byte in each file and its name. A compressed file keeps
  what its compression hides. Check: `apps/eval` `tests/test_scrubbed_artifacts.py`.
- The eval worker image carries Node 22.22.0 and promptfoo 0.125.1 for plugins. Check:
  `scripts/tests/test_eval_image_promptfoo.py` (`AISC_CHECK_EVAL_IMAGE=1` builds the image).
- Engine migration 0024 changes nothing; `manage.py clean_old_secrets` retires LangBiTe's `judge_api_key` and
  `judge_model` behind the cleanup's backup and dry run, printing `retired` lines after the keys to rotate.
  Check: `scripts/lib/engine-tests.sh aisc_backend.tests.test_langbite_judge_keys`.

### The audit's mechanical fixes (no behaviour change, nothing to do when upgrading)
- Every module: comments, READMEs and docstrings that no longer said what the code does now do; dead code
  (unused CSS on the launcher pages, unused routes, parameters and helpers) is gone; tests that proved nothing
  now check behaviour, and missing tests were added.
- The dashboard gateway has behaviour tests for its Superset hook and runs them on the image's PyJWT and
  cryptography versions; an empty keys address is refused when the gateway starts.
- The plugin-manager no longer has the unused `list_packages`/`close`; its wheel is vendored again into the
  engine and the eval worker. The guard's plugin-interface and plugin-manager pins follow their new commits.
- The system card renderer has no `/render/html` route; its ledger route exception is gone with it.
- Check: `cd scripts/tests && uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' pytest -q`
  and `scripts/guard-frozen.sh`.

### The audit's design changes
- Before upgrading: look at the rows still queued in the ledger outboxes. The relay now refuses camelCase
  author fields and more secret shapes (AKIA, hf_, Token, passwords in URLs), and an event the ledger cannot
  keep (NUL, keys that are not text, cycles, dates or BigInt in TypeScript) is refused when it is built.
- Upgrade the report generator together with the report composer: the composer asks the generator's new
  `POST /v1/style/check` whether a template's logo can be drawn, and takes the logo when it gets no answer.
- Access follows the gateway: when the gateway header is there, a Bearer next to it must name the same person
  (401 otherwise). Keycloak keys are fetched with a 3 s limit. `admit()` takes viewer, editor and owner.
- The dashboard gateway takes only an access token that carries exp, iat and iss, and a running Superset
  session syncs its roles again when oauth2-proxy refreshes the token. A membership database that cannot be
  read keeps a person's roles instead of removing them; stakeholder-group roles survive a sign-in.
- A stored key stays only while the address keeps its scheme, host and port (422 otherwise, type the key
  again). `secrets rotate` exits 1 while an old key is still needed. The protocol doors read at most 2 MiB
  and count a run key's use only for an accepted request; one OIP request makes at most 256 calls.
- Runs: a plugin runs in its own process group and anything it starts ends with it; a failure before or
  during a run fails that test once, stops the run and revokes its pass; the worker resolves only helpers of
  the run's own project. Each observation names the run that made it (engine migration 0026).
- Every call between services gives up after a set time and reads a wrong-shaped answer as an error.
- The launcher pages and the composer serve their own fonts (no Google), from one launcher stylesheet; the
  platform decides which tools are greyed and where each dashboard tile opens.
- One table (`scripts/suites.py`) says how every suite runs, for `verify.sh` and CI; image tags are exact and
  checked; the read-only database checks have a Python harness (`python3 -m stackcheck db-access`).
- Check: as above, plus `bash scripts/test-platform.sh -q`.

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
