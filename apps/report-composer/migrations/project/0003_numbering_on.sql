-- Reports are numbered (1, 1.1, A) by default, and so are the reports of every layout stored before
-- this. The Numbering box stays, so an editor can still turn it off for one layout.
ALTER TABLE report_composer.layout ALTER COLUMN numbering SET DEFAULT true;
UPDATE report_composer.layout SET numbering = true WHERE NOT numbering;
