-- The card versions of this project.
--
-- One row per saved AI card, numbered 1, 2, ... in this database. The database is the project, so
-- there is no project_id column (the shared-database layout had one, in core.system). The platform
-- (platform_rw, the owner of this database) is the only writer; every module reads it and points
-- its own keys at project.system (pid). Only the latest version may change, and no version changes
-- its number.
--
-- Keep the column order: the move tool (platform_service.isolate) compares rows in target column order.
CREATE SCHEMA IF NOT EXISTS project;
COMMENT ON SCHEMA project IS 'This project''s AI card versions: one row per saved card, numbered 1, 2, ...';

CREATE TABLE IF NOT EXISTS project.system (
    pid         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    number      integer NOT NULL CHECK (number > 0) UNIQUE,
    name        text NOT NULL,
    version     text,
    provider    text,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text
);
COMMENT ON TABLE project.system IS
    'One saved AI card version of this project''s one AI system; number 1, 2, ...';

CREATE OR REPLACE FUNCTION project.system_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF NEW.number <> OLD.number OR OLD.number < (SELECT max(number) FROM project.system) THEN
    RAISE EXCEPTION 'system version % is not the latest and cannot change', OLD.number;
  END IF;
  RETURN NEW;
END $f$;

DO $t$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'system_only_latest_changes'
                  AND tgrelid = 'project.system'::regclass) THEN
    CREATE TRIGGER system_only_latest_changes BEFORE UPDATE ON project.system
      FOR EACH ROW EXECUTE FUNCTION project.system_only_latest_changes();
  END IF;
END $t$;

-- Nobody but the owner writes it. The module roles read it and may point a foreign key at it
-- (REFERENCES); the two readers only read it. A role that does not exist is skipped.
REVOKE ALL ON project.system FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['qualification_rw', 'control_objectives_rw', 'controls_rw', 'engine_rw',
                           'report_composer_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA project TO %I', r);
      EXECUTE format('GRANT SELECT, REFERENCES ON project.system TO %I', r);
    END IF;
  END LOOP;
  FOREACH r IN ARRAY ARRAY['report_ro', 'dashboard_ro'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA project TO %I', r);
      EXECUTE format('GRANT SELECT ON project.system TO %I', r);
    END IF;
  END LOOP;
END $g$;
