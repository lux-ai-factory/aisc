-- 2026-10-01: reports are numbered (1, 1.1, A) by default, retroactively: every layout stored before this
-- numbers its report too. The Numbering box stays, so an editor can still turn it off for one layout.
ALTER TABLE report_composer.layout ALTER COLUMN numbering SET DEFAULT true;
UPDATE report_composer.layout SET numbering = true WHERE NOT numbering;
