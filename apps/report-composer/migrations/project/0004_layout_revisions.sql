-- Every revision of a layout is kept, for the ledger. A save replaces the layout's blocks; the
-- revision it made is written here first and never changed or removed (append-only, TRUNCATE refused).
-- No key to the layout: its revisions outlive it. The table's owner (the role migrations run as) can
-- still drop the triggers; the ledger's frozen states are the check on that.
CREATE TABLE report_composer.layout_revision (
    layout_id uuid NOT NULL,
    revision  integer NOT NULL CHECK (revision >= 1),
    state     jsonb NOT NULL,
    saved_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (layout_id, revision)
);

CREATE FUNCTION report_composer.layout_revision_is_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'layout revisions are append-only: they are never changed, removed or truncated';
END $$;

CREATE TRIGGER layout_revision_is_append_only BEFORE UPDATE OR DELETE ON report_composer.layout_revision
  FOR EACH ROW EXECUTE FUNCTION report_composer.layout_revision_is_append_only();
CREATE TRIGGER layout_revision_is_never_truncated BEFORE TRUNCATE ON report_composer.layout_revision
  FOR EACH STATEMENT EXECUTE FUNCTION report_composer.layout_revision_is_append_only();

-- the revisions of the layouts stored before this
INSERT INTO report_composer.layout_revision (layout_id, revision, state, saved_at)
SELECT l.id, l.revision,
       jsonb_build_object('name', l.name, 'description', l.description, 'template_id', l.template_id::text,
                          'revision', l.revision, 'show_index', l.show_index, 'numbering', l.numbering,
                          'blocks', coalesce((SELECT jsonb_agg(jsonb_build_object('instance_id', b.instance_id::text,
                                                                                  'block_type', b.block_type,
                                                                                  'options', b.options)
                                                               ORDER BY b.position)
                                              FROM report_composer.layout_block b WHERE b.layout_id = l.id),
                                             '[]'::jsonb)),
       l.updated_at
  FROM report_composer.layout l;
