# shared/access-ts

The TypeScript client the Next.js applications (`qualification-web` in step 1, `controls-web` in step 4) use to
ask the platform whether a caller may do something in a project: `GET /authz/projects/{ref}?want={method}`.

## How it works

The rule of who may do what in a project lives once, in `aisc_identity.access` (`shared/identity`), and the
platform (service `platform`) serves it. This client sends the caller's token and the HTTP method, and passes the
verdict on; it decides nothing, so the Next.js applications cannot drift from the Python services.
[docs/architecture.md](../../docs/architecture.md#1-gateway-and-sign-in) explains how sign-in and these checks fit
together.

`admit(project, method, token, { platformUrl })` returns either the admission (`pid`, `slug`, `role`, `admin`,
`mayWrite`) or a refusal with status 403 or 404 and the platform's message. A platform that is not configured,
not reachable, slow (3 seconds by default) or answering something unexpected gives a 503: nobody gets in on a
guess.

## A project's database

`projectDb.mjs` (types in `projectDb.d.mts`) is the JavaScript twin of `aisc_identity.projectdb`: `databaseName(pid)`
(`project_` and the pid's 32 lowercase hex digits; only a canonical pid, in any case, names one), `pidOf(name)`,
`projectDsn(template, database, { driver })` and `maintenanceDsn(template)`. A template is a URL with `{database}` as
its path; Prisma's own options (`schema`, `connection_limit`, `pool_timeout`) are dropped and every libpq option is
kept. It is plain JavaScript so the apps' node scripts can import it too. Both twins run the shared cases in
`shared/identity/projectdb-cases.json`.

## Refusals and the card lock

`refusal.ts` is the TypeScript twin of `aisc_identity.refusal`: the `Refusal` type (the answer to a save that
would replace something the person has not seen) and `isRefusal(value)`. Both twins run the shared cases in
`shared/identity/refusal-cases.json`.

`cardLock.ts` is the twin of `aisc_identity.card_lock`: `cardLockExclusive(tx)` for the transaction that stores
a card, `cardLockShared(tx)` for a writer that reads the latest card to stamp a record. `tx` is a Prisma
transaction client; both refuse a client outside a transaction. With the Python helper they are the only code
that spells the lock's key.

`holds.ts` is the twin of `aisc_identity.holds`: `claimForSave(tx, kind, subject, part, label, personSubject,
personName)` claims a part of a task for the person saving, inside the Prisma transaction that writes, through the
project database's `work.claim_for_save`. Someone else holding the part, or the task being in check, throws
`HoldRefused`, whose `refusal` is the refusal object the page shows; the transaction then rolls back. Both twins run
the shared wording cases in `shared/identity/hold-refusal-cases.json`.

`cardChange.ts` reads the project database's `work.card_change()`: `cardChange(tx)` is the latest card state
(version, revision) with who stored its card and when, and `cardChangedSince(drawn, now)` the line a page drawn on
an earlier card state shows, "The AI card changed since you started (who, when).", or null while it is the latest.

`workParts.ts` is what a held page shows of who holds its parts: `readParts(project, kind, subject, opts)` reads
the task from the platform as the person using the page (null while the task does not exist yet), with what they
may do on each part as the platform says it (`canTake`, `canRelease`); `changePart(..., "take" | "release", opts)`
calls the platform's take or release; `holderLine(part)` is the line the page shows. A refusal is the platform's
own words.

## Settings

| Setting | Meaning | In the stack |
| --- | --- | --- |
| `PLATFORM_URL` (read by each app, passed as `platformUrl`) | the platform's address; empty means every request gets a 503 | `http://platform:8000` |

## Copies in the applications

qualification and controls are separate repositories with their own build contexts, so each keeps a copy:

| Here | In each app |
| --- | --- |
| `projectAccess.ts` | `src/vendor/aisc-access/projectAccess.ts` |
| `projectAccess.test.ts` | `test/vendor/projectAccess.test.ts` |
| `projectDb.mjs`, `projectDb.d.mts` | `src/vendor/aisc-access/` |
| `projectDb.test.ts` | `test/vendor/projectDb.test.ts` |
| `../identity/projectdb-cases.json` | `test/fixtures/projectdb-cases.json` |
| `refusal.ts`, `cardLock.ts`, `cardChange.ts`, `holds.ts`, `workParts.ts` | `src/vendor/aisc-access/` |
| `test/refusal.test.ts`, `test/cardChange.test.ts`, `test/holds.test.ts`, `test/workParts.test.ts` | `test/vendor/` |
| `../identity/refusal-cases.json` | `test/fixtures/refusal-cases.json` |

`test/vendor/inSync.test.ts` in each app fails when a copy differs from this folder (it is skipped when the app is
checked out without the aisc repository around it). To change a file, edit it here and copy it into both apps.
