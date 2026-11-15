-- The verified state of each ledger database becomes a log that only grows. Each state the platform verifies
-- (immudb's tx id and tx hash) is a new row that follows the one it replaces, never an update in place: what
-- was verified before stays, two workers advancing from the same state cannot both win (one row may follow
-- another), and an ordinary advance never moves back. A reanchor after a restore (an admin checked the
-- server's new head) is recorded as such and may move back.
--
-- platform_rw inserts and reads; nobody changes or removes a row, the owner included. ledger.state, the
-- table this replaces, is copied once and kept, readable only.
CREATE TABLE IF NOT EXISTS ledger.state_log (
    id          bigserial PRIMARY KEY,
    db          text NOT NULL,
    follows     bigint REFERENCES ledger.state_log (id),
    tx_id       bigint NOT NULL CHECK (tx_id >= 0),
    tx_hash     bytea NOT NULL,
    signature   bytea,
    kind        text NOT NULL CHECK (kind IN ('advance', 'reanchor')),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE NULLS NOT DISTINCT (db, follows)
);

CREATE OR REPLACE FUNCTION ledger.state_log_refuse_change() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  RAISE EXCEPTION 'ledger.state_log only grows: a verified state is never changed or removed';
END
$f$;

CREATE OR REPLACE TRIGGER state_log_append_only BEFORE UPDATE OR DELETE ON ledger.state_log
    FOR EACH ROW EXECUTE FUNCTION ledger.state_log_refuse_change();
CREATE OR REPLACE TRIGGER state_log_no_truncate BEFORE TRUNCATE ON ledger.state_log
    FOR EACH STATEMENT EXECUTE FUNCTION ledger.state_log_refuse_change();

-- A row follows the latest state of its own database, and an advance does not move back.
CREATE OR REPLACE FUNCTION ledger.state_log_moves_forward() RETURNS trigger LANGUAGE plpgsql AS $f$
DECLARE
  prior ledger.state_log;
BEGIN
  IF NEW.follows IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO prior FROM ledger.state_log WHERE id = NEW.follows;
  IF prior.db IS DISTINCT FROM NEW.db THEN
    RAISE EXCEPTION 'a state of % cannot follow a state of %', NEW.db, coalesce(prior.db, 'nothing');
  END IF;
  IF NEW.kind = 'advance' AND NEW.tx_id < prior.tx_id THEN
    RAISE EXCEPTION 'the verified state of % moves back from tx % to tx %', NEW.db, prior.tx_id, NEW.tx_id;
  END IF;
  RETURN NEW;
END
$f$;

CREATE OR REPLACE TRIGGER state_log_moves_forward BEFORE INSERT ON ledger.state_log
    FOR EACH ROW EXECUTE FUNCTION ledger.state_log_moves_forward();

INSERT INTO ledger.state_log (db, follows, tx_id, tx_hash, signature, kind, recorded_at)
SELECT s.db, NULL, s.tx_id, s.tx_hash, s.signature, 'advance', s.updated_at
  FROM ledger.state s
 WHERE NOT EXISTS (SELECT 1 FROM ledger.state_log l WHERE l.db = s.db);

REVOKE ALL ON ledger.state_log FROM PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES ON ledger.state_log FROM platform_rw;
GRANT SELECT, INSERT ON ledger.state_log TO platform_rw;
GRANT USAGE, SELECT ON SEQUENCE ledger.state_log_id_seq TO platform_rw;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES ON ledger.state FROM platform_rw;
GRANT SELECT ON ledger.state TO platform_rw;
