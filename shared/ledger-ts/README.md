# shared/ledger-ts

How the Next.js apps write a ledger event.

| File | What it does |
| --- | --- |
| `emit.ts` | `emitEvent(tx, event)` writes one event with the project database's `ledger.emit(jsonb)`, in the transaction of the change it describes. It cites the request the gateway witnessed and never names who acted. Nothing is written while `LEDGER_MODE` is off. |
| `gatewayToken.ts` | `throughGateway(headers)`: whether the request carries a gateway token that verifies (RS256, issuer, expiry, `azp` = the gateway's client), the witness's own rule. Only then is the request id cited. |
| `canonical.ts` | RFC 8785 canonical JSON, the twin of the platform's `ledger/canonical.py`, and `ledgerSafe`, which refuses before writing what the relay would refuse later. |

The Python services use `aisc_identity.ledger_events`, which follows the same rules.

qualification and controls are separate repositories with their own build
contexts, so each keeps a copy:

| Here | In each app |
| --- | --- |
| `*.ts` | `src/vendor/aisc-ledger/` |
| `*.test.ts` | `test/vendor/ledger/` |

`test/vendor/inSync.test.ts` in each app fails when a copy differs from this
folder. To change one of these files, edit it here and copy it into both apps.
