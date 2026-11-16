-- A review of the Evidence map stays on record after a change to the map ends it. A change of links or notes
-- used to delete the review row, so who had reviewed which link set was left only in the ledger. Now the row
-- is kept and marked ended (voided_at); at most one review per card version holds at a time. Safe on an
-- existing install: one empty column, and the one-row-per-version key becomes a unique index over the reviews
-- that hold; no row changes.
ALTER TABLE evidence.review ADD COLUMN IF NOT EXISTS voided_at timestamptz;
ALTER TABLE evidence.review DROP CONSTRAINT IF EXISTS review_pkey;
CREATE UNIQUE INDEX IF NOT EXISTS review_one_holding ON evidence.review (system_id) WHERE voided_at IS NULL;
COMMENT ON COLUMN evidence.review.voided_at IS
    'When a later change of the map ended this review; NULL while the review holds';
