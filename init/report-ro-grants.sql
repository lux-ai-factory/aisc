-- SELECT for report_ro on exactly the tables the report blocks read (02 D6 (b)). Superuser, safe
-- to run again. A table that does not exist yet is skipped, so it also runs on a database without
-- module schemas. No ALTER DEFAULT PRIVILEGES on module schemas: a table added later is not
-- readable until it is listed here.
\connect platform
DO $grants$
DECLARE
    s text;
    t text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
        RAISE EXCEPTION 'report_ro does not exist: run init/report-roles.sql first';
    END IF;
    FOREACH s IN ARRAY ARRAY['qualification', 'control_objectives', 'engine'] LOOP
        IF to_regnamespace(s) IS NOT NULL THEN
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO report_ro', s);
        END IF;
    END LOOP;
    FOREACH t IN ARRAY ARRAY[
        'qualification.qualification', 'qualification.card_component',
        'qualification.knowledge_graph', 'qualification.qualification_risk',
        'control_objectives.project', 'control_objectives.risk',
        'control_objectives.mapped_objective', 'control_objectives.mapping_run',
        'engine.project', 'engine.evaluation', 'engine.evaluation_plugin', 'engine.evaluation_input',
        'engine.plugin', 'engine.ai_component', 'engine.observation', 'engine.measurement',
        'engine.metric', 'engine.artifact'] LOOP
        IF to_regclass(t) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON %s TO report_ro', t);
        END IF;
    END LOOP;
    -- plugin_config.config may hold tool settings: only the columns that tie a run to its tool
    IF to_regclass('engine.plugin_config') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT (id, plugin_id) ON engine.plugin_config TO report_ro';
    END IF;
END
$grants$;

-- superset: chart ownership and the review comments (02 D5), nothing else (never ab_user)
SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'superset') AS has_superset \gset
\if :has_superset
\connect superset
DO $grants$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['public.aisc_comment', 'public.dashboards', 'public.dashboard_roles',
                             'public.ab_role', 'public.dashboard_slices', 'public.slices',
                             'public.tables'] LOOP
        IF to_regclass(t) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON %s TO report_ro', t);
        END IF;
    END LOOP;
END
$grants$;
\endif
