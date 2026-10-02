-- The one table that names people (ledger spec 6.1, 7.5; S8). In its own database, ledger_identity,
-- which no role but platform_rw may connect to: pgAdmin's read-all role can't see it.
-- A reference is random, so deleting a row really erases the link (I10); the MAC catches a row someone
-- edited (it covers the reference, the subject and the name).
CREATE TABLE IF NOT EXISTS identity.actor (
    scope      text NOT NULL,                 -- the project's pid, or 'platform' (never NULL: a unique key)
    actor_ref  text PRIMARY KEY CHECK (actor_ref ~ '^actor:[0-9a-f]{32}$'),
    sub        text NOT NULL,
    name       text NOT NULL,
    mac        text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (scope, sub)
);
