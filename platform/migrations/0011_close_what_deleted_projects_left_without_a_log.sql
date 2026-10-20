-- A project deleted while the ledger pool was empty never had a log: the witness records of its requests
-- and its platform events (its own deletion included) had nowhere to go, and the relay counted them as
-- pending on every pass. They are closed here, saying why; the rows stay. A project can no longer be
-- deleted before it has a log (routes/projects.py), so this only closes what was left before.
ALTER TABLE ledger.witness ADD COLUMN IF NOT EXISTS closed_at timestamptz;
ALTER TABLE ledger.witness ADD COLUMN IF NOT EXISTS closed_reason text;

UPDATE ledger.witness w
   SET closed_at = clock_timestamp(),
       closed_reason = 'no log: the project was deleted before it had one'
 WHERE w.delivered_seq IS NULL AND w.closed_at IS NULL AND w.project_pid IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM core.project p WHERE p.pid = w.project_pid)
   AND NOT EXISTS (SELECT 1 FROM ledger.pool l WHERE l.assigned_pid = w.project_pid);

UPDATE core.outbox o
   SET delivered_at = clock_timestamp(),
       delivered_reason = 'no log: the project was deleted before it had one'
 WHERE o.delivered_at IS NULL AND o.project_pid IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM core.project p WHERE p.pid = o.project_pid)
   AND NOT EXISTS (SELECT 1 FROM ledger.pool l WHERE l.assigned_pid = o.project_pid);
