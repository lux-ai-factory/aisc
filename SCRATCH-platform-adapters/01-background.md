# §0. Where the branches stand (background, 2 minutes)

> From `SCRATCH-platform-adapters-discussion.md` §0. Evidence read out of `origin/master`,
> `origin/dev`, `origin/feat/unified-modules` and `origin/pilot` on 2026-11-09.

Base of divergence: `f96264d` (2026-08-31, PR #60 "Merge pull request #60 from dev").

| branch | commits since `f96264d` | relation |
|---|---|---|
| `origin/master` | +38 | not contained in fm or pilot |
| `origin/dev` | +38 | close to master (shares `2ea88ca`) |
| `origin/feat/unified-modules` (fm) | +247 | superproject line never merged into pilot |
| `origin/pilot` | +25 | superproject line never merged into fm |

- **Submodules:** `pilot` is a strict superset of `feat/unified-modules` (fm is an ancestor in all 7 submodules; 0 commits unique to fm). So all submodule work is carried forward.
- **Superproject:** fm and pilot are *independent lines*, not a superset either way. The superproject was **rebuilt** on a 25-commit line.
- **Only 5 superproject files** exist on fm but not pilot, and pilot deliberately deleted all 5 in commit `7de2c5c` (`init/catalogue-role.sql`, `keycloak/verify_token.py`, `keycloak/e2e/test_sso_selenium.py`, `apps/report-composer/migrations/library/000{1,2}_*.sql`).
- **But pilot also drops 23 master files** (the whole Playwright `e2e/` suite, the published-image `docker-compose.yml` / `-build` / `-infra`, `env.development`, `env.example`, `docs/DEVELOPER_GUIDE.md`, `keycloak/aisc-realm.template.json`, `init/{controls,qualification}-db.sql`). Some look intentional (compose/env renamed); **the e2e suite and published-compose stack look like possible regressions**.
- Top-level tree diff for a "reset to pilot": **740 files, +121,391 / −2,467** vs master; fm→pilot is **277 files, +8,288 / −3,101**.

**Point to make:** a "big merge / reset" to pilot is safe at the submodule level, but at the superproject level it is a rewrite, not a merge — confirm what we are happy to drop from master (e2e, published compose).

**Agreed framing (meeting, 2026-11-11): these are exploration branches.** `pilot` and
`feat/unified-modules` are **scratch projects at the scale of the whole app**, not release lines. We use them
as **discussion points** to define features, and fold in the **features** — the implementation and
architecture may change completely. So the reset is judged **feature by feature**, never merged. Full
statement: [`../docs/exploration-branches.md`](../docs/exploration-branches.md).

---

*See [`03-code-smells.md`](03-code-smells.md) for the "dropped e2e suite" and "generated env" smells, and
[`08-meeting-agenda.md`](08-meeting-agenda.md) for the reset decision.*
