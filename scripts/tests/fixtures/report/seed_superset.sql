-- Seed of the `superset` database (the seven tables the report reads), report test bed. Superuser.
-- Alpha's dashboard 10 holds charts 33 and 34, Beta's 20 holds 35, Echo's 50 holds 36.
-- Role names: 'AiscProject_' || pid without dashes (apps/results-dashboard/aisc_ext/projects.py).
SET session_replication_role = replica;
INSERT INTO ab_role (id, name) VALUES
  (1, 'AiscProject_a0000000000040008000000000000001'),
  (2, 'AiscProject_b0000000000040008000000000000001'),
  (5, 'AiscProject_e0000000000040008000000000000001'),
  (9, 'Admin');
INSERT INTO dashboards (id, dashboard_title, slug, published, uuid) VALUES
  (10, 'Alpha results', 'aisc-a0000000000040008000000000000001', true, gen_random_uuid()),
  (20, 'Beta results BETAMARK', 'aisc-b0000000000040008000000000000001', true, gen_random_uuid()),
  (50, 'Echo results', 'aisc-e0000000000040008000000000000001', true, gen_random_uuid());
INSERT INTO dashboard_roles (id, role_id, dashboard_id) VALUES (1, 1, 10), (2, 2, 20), (5, 5, 50);
INSERT INTO tables (id, table_name, database_id, schema) VALUES
  (100, 'engine_results_a0000000000040008000000000000001', 1, NULL),
  (101, 'controls_answers_a0000000000040008000000000000001', 2, NULL),
  (200, 'engine_results_b0000000000040008000000000000001', 3, NULL),
  (500, 'engine_results_e0000000000040008000000000000001', 5, NULL);
INSERT INTO slices (id, slice_name, datasource_type, viz_type, datasource_id, uuid) VALUES
  (33, 'Bias rate by version', 'table', 'echarts_timeseries_bar', 100, gen_random_uuid()),
  (34, 'Checklist scores', 'table', 'table', 101, gen_random_uuid()),
  (35, 'Beta chart BETAMARK', 'table', 'table', 200, gen_random_uuid()),
  (36, 'Echo accuracy', 'table', 'table', 500, gen_random_uuid());
-- the chart later in the alphabet is the newer one, so a list by date differs from a list by name
UPDATE slices SET changed_on = '2026-01-01 10:00' WHERE id = 33;
UPDATE slices SET changed_on = '2026-02-01 10:00' WHERE id = 34;
INSERT INTO dashboard_slices (id, dashboard_id, slice_id) VALUES (1, 10, 33), (2, 10, 34), (3, 20, 35), (5, 50, 36);
-- comments are keyed by dashboard_id text: the id or the slug; created_at without time zone, read as UTC
INSERT INTO aisc_comment (id, dashboard_id, chart_id, parent_id, author_sub, author_name, body, created_at) VALUES
  (1, '10', 33, NULL, 'alice', 'Alice Editor', 'First look: bias is down <script>x</script>', '2026-09-12 10:00'),
  (2, '10', 33, 1, 'olga', 'Olga Owner', 'Agreed, reply text', '2026-09-12 11:00'),
  (3, 'aisc-a0000000000040008000000000000001', 33, NULL, 'victor', 'Victor Viewer', 'Second root comment', '2026-09-13 09:00'),
  (4, '20', 33, NULL, 'bob', 'Bob', 'LEAK comment BETAMARK on the same chart id', '2026-09-12 09:00'),
  (5, '10', 34, NULL, 'alice', 'Alice Editor', 'Comment on the other chart OTHERCHART', '2026-09-12 09:30'),
  (6, '20', 35, NULL, 'bob', 'Bob', 'Beta comment BETAMARK', '2026-09-12 09:00'),
  (7, '50', 36, NULL, 'erin', 'Erin', 'Echo comment', '2026-09-06 09:00');
SET session_replication_role = origin;

-- what Save to report stored: one vector file per plot, with its filters as text and the rows its chart drew (NULL:
-- saved without a count) (the table: schema_superset.sql)
INSERT INTO aisc_report_plot (dashboard_id, chart, tab, tags, svg, sha256, comment, author_name, created_at, rows, save_id) VALUES
  (10, 'By register', 'First tab', '["Model: OpenAI"]', convert_to('<svg xmlns="http://www.w3.org/2000/svg"><text>old</text></svg>','UTF8'), 'old', 'older comment', 'Alice', '2026-01-01 10:00', 5, 'save-old'),
  (10, 'By community', 'First tab', '["Model: OpenAI"]', convert_to('<svg xmlns="http://www.w3.org/2000/svg"><text>com</text></svg>','UTF8'), 'com', 'only in the older save', 'Alice', '2026-01-01 10:00:01', 4, 'save-old'),
  (10, 'By register', 'First tab', '["Model: OpenAI"]', convert_to('<svg xmlns="http://www.w3.org/2000/svg"><text>new</text></svg>','UTF8'), 'new', 'Newest comment', 'Alice', '2026-02-01 10:00:00', 2, 'save-new'),
  (10, 'By register', 'First tab', '["Model: Local"]', convert_to('<svg xmlns="http://www.w3.org/2000/svg"><text>loc</text></svg>','UTF8'), 'loc', '', 'Alice', '2026-02-01 10:00:01', 1, 'save-new'),
  (10, 'By category', 'First tab', '[]', convert_to('<svg xmlns="http://www.w3.org/2000/svg"><text>cat</text></svg>','UTF8'), 'cat', '', 'Alice', '2026-02-01 10:00:02', NULL, 'save-new'),
  (20, 'Other', '', '[]', convert_to('<svg xmlns="http://www.w3.org/2000/svg"><text>oth</text></svg>','UTF8'), 'oth', 'another project', 'Bob', '2026-02-02 10:00', 3, 'save-b');
