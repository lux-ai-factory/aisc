-- Reports are numbered by default: every saved preset numbers the layouts made from it, including
-- those whose numbering was null (the default, which was off before this).
UPDATE report_library.preset SET numbering = true WHERE numbering IS DISTINCT FROM true;
