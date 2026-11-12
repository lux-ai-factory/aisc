# Appendix 9: Security

Back to [How AISC works](../architecture.md).

Who may do what, where the secrets are, and the limits of what AISC protects.

## Who may do what

- **Signed in**: anyone with an account in the realm `aisc` may create a project and becomes its owner.
- **In a project**: a viewer reads, an editor changes, an owner also manages the members. The realm role `admin`
  counts as owner of every project and alone may delete a project, install a test, update a private catalogue, set a
  local test's dimensions, register connections and choose the AI assistants' models and keys.
- **Every service checks the caller itself** (see [Flows](flows.md#signing-in-and-one-request)); the gateway's check
  is not the only one.
- **Internal routes** (service to service) are refused at the gateway and need a token per caller, made by
  `scripts/secrets.sh`.

## Secrets

- **Made at install** by `scripts/secrets.sh` into `env.secrets`, never committed: database passwords, tokens between
  services, signing keys.
- **Entered in the pages** (connection secrets, helper model keys, the AI assistants' keys): encrypted in the
  project's database with `PLATFORM_SECRETS_KEY` (a list, newest first, so it can be rotated) and never shown again.
- **During a test run**: the assessed system's secrets stay in the platform, which adds them to each call; a test
  holds only a short-lived run key (12 hours by default, `CONNECTIONS_RUN_KEY_TTL_S`, ending with the run). A helper
  model's key is given to the test, which calls the helper model itself.

## Network

- Only 80, 8100 and 8188 are published (443 on an https install); each sends an anonymous request to sign in.
  Keycloak is on `127.0.0.1:8081`. Databases, queues and storage publish nothing unless `AISC_ADMIN_PORTS=on`.
- **Calls to the assessed system** go to public addresses; internal or private ones are refused unless the project
  allows that host (Manage > Components and connections) or the stack does (`CONNECTIONS_ALLOWED_HOSTS`). The
  stack's own services, loopback and cloud metadata addresses can never be allowed from the page.
- **Test code is not sandboxed.** The worker that runs it is on the `backend` network with the platform, the
  databases and the queues. The platform's doors keep the assessed system's secrets away from a test, and the
  address checks protect an honest test from a wrong connection, but a malicious test can reach any service on that
  network. Install only tests you trust: installing takes the admin role for that reason, and builds run without
  secrets.
- **Superset's cache** is on a network of its own, because Superset unpickles what it reads from it.

## Record of who did what

Every write through the gateway is witnessed and every change writes an event in the same transaction, relayed into
the project's immudb database ([Flows](flows.md#the-ledger)). Entries are checked before they are shown, and an
export can be checked offline. The ledger holds person references, never names; the link to the person can be
erased ([Manage](manage.md#logs)).
