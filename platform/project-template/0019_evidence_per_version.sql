-- Step 4 links belong to one AI card version: a link is (card version, objective, test or control).
-- A link without a version is given the project's latest one. Deleting a card version deletes its
-- links. Safe to run again.
ALTER TABLE evidence.link ADD COLUMN IF NOT EXISTS system_id uuid;

UPDATE evidence.link SET system_id = (SELECT pid FROM project.system ORDER BY number DESC LIMIT 1)
 WHERE system_id IS NULL;
-- a link with no card version at all cannot be shown anywhere
DELETE FROM evidence.link WHERE system_id IS NULL;
ALTER TABLE evidence.link ALTER COLUMN system_id SET NOT NULL;

DO $v$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'link_system_id_fkey'
                   AND conrelid = 'evidence.link'::regclass) THEN
    ALTER TABLE evidence.link ADD CONSTRAINT link_system_id_fkey
      FOREIGN KEY (system_id) REFERENCES project.system (pid) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'evidence.link'::regclass AND contype = 'p'
                   AND pg_get_constraintdef(oid) = 'PRIMARY KEY (system_id, objective_id, kind, item_key)') THEN
    EXECUTE (SELECT 'ALTER TABLE evidence.link DROP CONSTRAINT ' || quote_ident(conname) FROM pg_constraint
              WHERE conrelid = 'evidence.link'::regclass AND contype = 'p');
    ALTER TABLE evidence.link ADD CONSTRAINT link_pkey PRIMARY KEY (system_id, objective_id, kind, item_key);
  END IF;
END
$v$;
