# Appendix — evidence index (file:line)

> From `SCRATCH-platform-adapters-discussion.md` evidence index, extended with the 2026-11-11 refs
> (code smells, feature flags). Read against `origin/pilot` (and the other refs) on 2026-11-09 unless
> noted; new refs verified in the working tree on 2026-11-11.

**Superproject topology**
- `git merge-base` fm/pilot = `f96264d`; master/dev `+38`, fm `+247`, pilot `+25` since it.
- fm-only superproject files: `init/catalogue-role.sql`, `keycloak/verify_token.py`, `keycloak/e2e/test_sso_selenium.py`, `apps/report-composer/migrations/library/000{1,2}_*.sql` (deleted on pilot in `7de2c5c`).
- master-only superproject files: `e2e/*`, `docker-compose*.yml`, `env.development`, `env.example`, `docs/DEVELOPER_GUIDE.md`, `keycloak/aisc-realm.template.json`, `init/{controls,qualification}-db.sql`, …

**One DB per project**
- `platform/platform_service/projectdb.py:34-38,63-77,94-97`
- `platform/platform_service/routes/projects.py:75,89-104`
- `platform/project-template/0001_controls.sql:7-15`, `0007_qualification.sql:11-27`, `0020_ledger_outbox.sql:87`
- `platform/platform_service/db.py:283-303`
- `scripts/db_consistency/{checks,heads}.py`, `scripts/superset_upgrade_check.py`, `scripts/report-grants.sh`
- `platform/project-template/*.sql` — **27 files** (count, working tree 2026-11-11)

**Secrets / run keys / adapters**
- `apps/eval aisc_eval/celery_tasks.py:110-165` (whitelist + run pass), `:64-104` (`build_secret_environment`), `:545-572` (helper keys), `:672-673`
- master: `apps/eval aisc_eval/celery_tasks.py:319-330,395`
- `shared/plugin-interface src/aisc_plugin_interface/connections.py:1-30`
- `platform/platform_service/adapters.py:1-16,24`
- `platform/project-template/0026_connection_adapter_kinds.sql`
- `adapters/README.md` (folder + `docker restart platform`, lines 16-33)
- `platform/platform_service/secret_box.py:33-108,139-192`, `run_passes.py:33-87`, `connection_allowlist.py:31-207`

**Versioning**
- `platform/platform_service/db.py:330-371`
- `platform/project-template/0006_project_system.sql:27-42`, `0019_evidence_per_version.sql:4-24`
- `platform/migrations/0002_one_ai_system_per_project.sql:23-44` then `0003_card_versions_in_core_system.sql:39-76`
- `apps/backend aisc_backend/signals/system_stamp.py:19-21`

**Platform vs backend duplication**
- `apps/backend aisc_backend/models/ai_system.py:6-64`
- `apps/webapp src/components/AISystemSettings.tsx:14-222`
- `platform/platform_service/evidence.py:93-196`, `dashboards.py:24-34`, `routes/connections.py`, `connection_store.py`

**Launcher / suites / ports (secondary)**
- `homepage/assets/{page.js,launcher.css,origins.js,ledger-beacon.js}`, `homepage/*.html`
- `scripts/suites.py:21-99`, `.github/workflows/ci.yml:32-59,126-178`, `scripts/tests/test_suites.py:28-30`
- `scripts/aisc.py:105-112,656-658,854-915`
- `.github/workflows/port-fallback.yml:9-10`, `scripts/tests/test_busy_ports.py:23`

**Code smells (2026-11-11, working tree)**
- Two project-DB modules: `platform/platform_service/projectdb.py`, `apps/backend/aisc_backend/projectdb.py`
- `platform/platform_service` = **12,489** lines; `platform/tests` = **21,569** lines (`wc -l`)
- `scripts/` = **~25,400** lines of Python, ~40 scripts; `scripts/aisc.py` = **1,906** lines
- compose service definitions: `docker-compose.development.yml` = **29**, `docker-compose-infra.development.yml` = **24**
- migration tools: `apps/backend/aisc_backend/migrations` (Django), `apps/controls/prisma`, `apps/qualification/prisma` (Prisma), `apps/control-objectives/alembic.ini`, `apps/report-composer/migrations` (Alembic), `platform/migrations` (SQL), `platform/project-template/*.sql` (per project)
- duplicated membership: `platform/platform_service/membership.py`, `apps/backend/aisc_backend/auth/membership.py`
- duplicated secrets: `platform/platform_service/secret_box.py` (196) vs `apps/backend/aisc_backend/config_secrets.py` (296) + `secret_cleanup.py` (135) + `config_secret_fields.py` (228)
- raw SQL into the engine tables: `platform/platform_service/evidence.py:582,781`, `dashboards.py:7-16` (psycopg; `db.py:13,260-271`)
- the project bridge: `apps/backend/aisc_backend/platform_projects.py`, `platform_helpers.py`

**Deployment mode / feature flags (2026-11-11, working tree)**
- the mode: `apps/backend/aisc_backend/deployment.py:1-146`; worker copy `apps/eval/aisc_eval/deployment.py:1-57`
- app-graph fork: `apps/backend/config/settings.py:132-154`; URLconf `apps/backend/config/urls.py:56`; app-ready `aisc_backend/apps.py:33`
- request forks: `aisc_backend/routers/project.py:130`, `routers/target_input.py:72`
- worker forks: `apps/eval/aisc_eval/service/api_client.py:29`, `apps/backend/aisc_backend/services/celery_service.py:78`
- schema forks: `aisc_backend/migrations/0019_no_login_of_its_own.py:34`, `0021_engine_deployment_marker.py`; guard `deployment.py:95-101`
- door: `apps/backend/aisc_backend/project_door.py:1-48`
