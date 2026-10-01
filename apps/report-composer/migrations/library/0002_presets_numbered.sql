-- 2026-10-01: reports are numbered by default, retroactively: every saved preset numbers the layouts made
-- from it (null meant "the default", which was off).
UPDATE report_library.preset SET numbering = true WHERE numbering IS DISTINCT FROM true;
