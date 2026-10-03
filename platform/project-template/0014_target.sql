-- What an assessment is about: the system, and each component the AI
-- card lists (its Components block, keyed by the card's stable component key). Every evaluation
-- names one, so every result says what it assessed. Written only by the platform; mirrored in the
-- engine as one `resource` component each (engine_component), which the evaluation form offers.
-- No secret here: the readers (report renderer, dashboard) read it to show each result's target.
CREATE SCHEMA IF NOT EXISTS target;

CREATE TABLE IF NOT EXISTS target.target (
    key               text PRIMARY KEY CHECK (key = 'system' OR key ~ '^component:[0-9a-f-]{36}$'),
    kind              text NOT NULL CHECK (kind IN ('system', 'component')),
    component_kind    text NULL,
    label             text NOT NULL CHECK (length(btrim(label)) BETWEEN 1 AND 200),
    first_card_number integer NULL,
    last_card_number  integer NULL,
    engine_component  uuid NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'system') = (key = 'system')),
    CHECK ((kind = 'system') = (component_kind IS NULL))
);

REVOKE ALL ON SCHEMA target FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA target FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['report_ro', 'dashboard_ro'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA target TO %I', r);
      EXECUTE format('GRANT SELECT ON target.target TO %I', r);
    END IF;
  END LOOP;
END $g$;

COMMENT ON SCHEMA target IS 'What each assessment is about: the system or one of its components (platform-owned).';
