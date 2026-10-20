# shared/access-ts

The TypeScript client of the platform's `GET /authz/projects/{ref}?want={method}`.

The rule of who may do what in a project lives once, in `aisc_identity.access`
(`shared/identity`), and the platform serves it. This client asks and passes the
verdict on; it decides nothing.

qualification and controls are separate repositories with their own build
contexts, so each keeps a copy:

| Here | In each app |
| --- | --- |
| `projectAccess.ts` | `src/vendor/aisc-access/projectAccess.ts` |
| `projectAccess.test.ts` | `test/vendor/projectAccess.test.ts` |

`test/vendor/inSync.test.ts` in each app fails when a copy differs from this
folder. To change the client, edit it here and copy both files into both apps.
