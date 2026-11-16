-- How long a project keeps its runs: off (no row) unless an owner sets 1 to 3650 days. The daily sweep
-- (platform_service/retention.py) deletes the runs that ended before the period, each with a tombstone and a
-- ledger event, as an owner's deletion does. A table of its own: core.project stays the superuser's
-- (init/platform-db.sql). The row goes with its project (db.delete_project).
CREATE TABLE IF NOT EXISTS core.project_retention (
    pid     uuid PRIMARY KEY,
    days    integer NOT NULL CHECK (days BETWEEN 1 AND 3650),
    set_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    set_by  text NOT NULL
);

REVOKE ALL ON core.project_retention FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.project_retention TO platform_rw;
