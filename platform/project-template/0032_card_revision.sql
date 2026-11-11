-- The number of the card's latest revision, set when the description of the latest version is corrected
-- in place. A new version starts at 1.
ALTER TABLE project.system ADD COLUMN IF NOT EXISTS card_revision integer NOT NULL DEFAULT 1
    CHECK (card_revision > 0);
