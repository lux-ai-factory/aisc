-- A frozen content may be redacted: its value goes (content NULL) and the row keeps when and why. The
-- ledger.content.redacted entry in the project's log names each redacted event id with the same reason,
-- so an export marks the line `content_redacted` and the checker accepts the mark only when the log backs it
-- (platform_service/ledger/secret_cleanup.py, scripts/verify-ledger-export.py). Schema only: the redaction
-- itself is run on the operator's word by scripts/clean-old-secrets.sh.
ALTER TABLE ledger.content ADD COLUMN IF NOT EXISTS redacted_at timestamptz;
ALTER TABLE ledger.content ADD COLUMN IF NOT EXISTS redaction text;

DO $marked$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'content_redaction_marked'
                 AND conrelid = 'ledger.content'::regclass) THEN
    ALTER TABLE ledger.content ADD CONSTRAINT content_redaction_marked
      CHECK ((redacted_at IS NULL) = (redaction IS NULL) AND (redacted_at IS NULL OR content IS NULL));
  END IF;
END
$marked$;
