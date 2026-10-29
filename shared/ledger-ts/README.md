# shared/ledger-ts

How the Next.js applications (`qualification-web` in step 1, `controls-web` in step 4) write an event to the
ledger, AISC's tamper-evident activity log. The Python services do the same with `aisc_identity.ledger_events`
(`shared/identity`), which follows the same rules.

## How it works

An application writes its event into the project database's `ledger` schema (the outbox) with
`ledger.emit(jsonb)`, in the same transaction as the change it describes: a rolled-back change leaves no event,
and a committed one always has one. The event never names who acted. It cites the request the gateway witnessed
(`X-AISC-Request-Id`), and the platform's relay takes the person from that witness record and moves the event into
the project's own immudb database. The ledger's place in AISC is in
[docs/architecture.md](../../docs/architecture.md) and, in detail, in
[docs/guide.md](../../docs/guide.md#how-it-works).

## Files

| File | What it does |
| --- | --- |
| `emit.ts` | `emitEvent(tx, event)` writes one event with `ledger.emit(jsonb)` on the caller's transaction and returns its event id. It cites the request the gateway witnessed and never names who acted. Nothing is written while `LEDGER_MODE` is off. |
| `gatewayToken.ts` | `throughGateway(headers)`: whether the request carries a gateway token that verifies (RS256, issuer, expiry, `azp` = the gateway's client), the witness's own rule. Only then is the request id cited. |
| `canonical.ts` | RFC 8785 canonical JSON, the twin of the platform's `ledger/canonical.py`, and `ledgerSafe`, which refuses before writing what the relay would refuse later. |

## Settings

Read from the application's environment.

| Setting | Meaning | Default | In the stack |
| --- | --- | --- | --- |
| `LEDGER_MODE` | `record` or `enforce` writes events; anything else writes none | `off` | `record` |
| `AUTH_ENABLED` | with it off (local work), nothing is verified and the presented request id is kept | `true` | `true` |
| `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URL` | the realm the gateway token is verified against; without them no request id is kept | none | realm `aisc` |
| `AISC_GATEWAY_CLIENT_ID` | the gateway's client, which the token's `azp` must name | `aisc-gateway` | default |

## Copies in the applications

qualification and controls are separate repositories with their own build contexts, so each keeps a copy:

| Here | In each app |
| --- | --- |
| `*.ts` | `src/vendor/aisc-ledger/` |
| `*.test.ts` | `test/vendor/ledger/` |

`test/vendor/inSync.test.ts` in each app fails when a copy differs from this folder (it is skipped when the app is
checked out without the aisc repository around it). To change one of these files, edit it here and copy it into
both apps.
