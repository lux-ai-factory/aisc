-- A stored file the platform was to delete (a purged run's artifact, a deleted project's dataset) but the
-- store would not: kept here with its project until a later sweep removes it (platform_service/run_purge.py),
-- so no file is forgotten in a shared bucket. The project may be gone already: no reference to core.project.
CREATE TABLE IF NOT EXISTS core.leftover_object (
    pid             uuid NOT NULL,
    bucket          text NOT NULL,
    name            text NOT NULL,
    first_failed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (bucket, name)
);

REVOKE ALL ON core.leftover_object FROM PUBLIC;
GRANT SELECT, INSERT, DELETE ON core.leftover_object TO platform_rw;
