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

`test/vendor/inSync.test.ts` in each app fails when a copy differs from this folder (it is skipped when the app is
checked out without the aisc repository around it). To change the client, edit it here and copy both files into
both apps.
