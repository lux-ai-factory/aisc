-- Manage -> Connections: the internal hosts this project's connections may reach (allowlist task
-- 2026-09-29). An entry is a host or host:port, lower case; the deployment's
-- CONNECTIONS_ALLOWED_HOSTS is a floor on top of these, never stored here. The stack's own services
-- and cloud metadata addresses are refused by the platform before an entry is written, and again
-- at every call. Edited by the project's owners and platform admins; who and when is kept, the
-- history of changes is left to the audit trail (immudb, later).
CREATE TABLE IF NOT EXISTS connection.allowed_host (
    host       text PRIMARY KEY CHECK (host = lower(host) AND length(host) BETWEEN 1 AND 260),
    note       text NULL CHECK (note IS NULL OR length(note) <= 200),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL
);

REVOKE ALL ON connection.allowed_host FROM PUBLIC;
