-- SELECT for report_ro on the superset tables the report reads (report run 02 D5, D6 (b)).
-- Superuser, safe to run again, run by scripts/report-grants.sh on every start. A table that does
-- not exist yet is skipped, so it also runs where superset has not migrated.
--
-- Since the isolation (2026-09-25, I2.7) the module tables are no longer in `platform`: report_ro
-- reads them inside each project database, where report-grants.sh grants the I2.6 list.
DO $check$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
        RAISE EXCEPTION 'report_ro does not exist: run init/report-roles.sql first';
    END IF;
END
$check$;

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
