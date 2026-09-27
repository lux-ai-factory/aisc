# One database per project: roadmap

**Decision (2026-09-23, final):** every project is completely isolated from the
others. Everything from step 1 (qualification) to step 6 (dashboard) belongs to
one project and lives in that project's own Postgres database. The only thing
that connects projects is the homepage.

## What stays shared, and why

| Shared | Why it cannot be per project |
|---|---|
| `platform` database, `core.project` + `core.project_member` | The homepage lists projects and decides who may open which, before any project is entered. |
| The catalogue | It's hosted online: one catalogue for every platform and every project. It knows no projects. When you install something, you choose which project it goes into, and the install is recorded in that project's database. |
| Keycloak (`keycloak` database) | Signing in is how you reach the homepage. It holds accounts, not project data. |
| Superset metadata (`superset` database) | One Superset instance. Each project gets its own database connection in it, and only that project's members can open it (Plan 6). |
| Plugin code on `PLUGIN_PATH`, and the devpi index | Code, not data. Which plugins a project uses is recorded in that project's database. |

Everything else moves into `project_<pid without hyphens>`, one schema per
module, with the same module roles as today (`controls_rw`, `qualification_rw`, …).

## Plans, in order

Each plan leaves the stack working and passing `scripts/verify.sh`.

1. **Project databases, and controls installed from the catalogue** —
   `2026-09-23-project-databases-1-controls.md`. The platform creates a
   database per project. Controls moves into it. A checklist reaches a project
   only by being installed from the catalogue in one click, into the project
   the user chooses.
2. **Qualification.** `qualification` schema per project. `core.system` moves
   into the project database as `project.system`, and the platform stops
   writing it.
3. **Control objectives.** `control_objectives` schema per project. Its own
   `project` table goes, because the database is the project.
4. **Engine.** Django backend and Celery worker route per project database.
   Django's users and sessions stay per project database too (created from the
   Keycloak token on first request). `public` models go.
5. **Dashboard.** One Superset database connection per project, registered by
   the platform when it creates the project. Dataset and dashboard copies per
   project. Superset access limited to that project's members.
6. **Retire the shared module schemas.** Drop `qualification`,
   `control_objectives`, `engine` and `core.system` from the
   `platform` database. Rewrite `verify-one-database.sh` as
   `verify-project-databases.sh`.

## Known costs, accepted with the decision

- **No database-enforced link to `core.project`.** A foreign key cannot cross
  databases. The database *is* the project, so rows carry no `project_id`.
- **Nothing can see across projects.** There will be no dashboard or query
  spanning projects.
- **Connections grow with projects.** Each app opens pools per project database.
  Plan 1 caps controls at 2 connections per project database. PgBouncer in front
  of Postgres is needed before about 10 live projects (`max_connections` = 100).
- **Migrations run per project database.** Each module's `*-migrate` service
  loops over every `project_%` database. A module also migrates a project
  database the first time it opens it.
