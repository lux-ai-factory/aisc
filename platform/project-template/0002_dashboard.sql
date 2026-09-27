-- WP11, the dashboard: it reads this project's answers as dashboard_ro, so it may connect
-- and look into the controls schema. The SELECT on the tables is granted by controls' own
-- migration (20260923210100_dashboard_reads_controls), because controls_rw owns them.
-- Nothing here lets it write.
DO $grant$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO dashboard_ro', current_database());
END
$grant$;
GRANT USAGE ON SCHEMA controls TO dashboard_ro;
