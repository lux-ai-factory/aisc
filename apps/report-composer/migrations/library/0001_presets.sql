-- The install-wide library of saved report structures (isolation 2026-09-25, 01-specs.md I8.2, D4).
--
-- A saved structure holds no project data and is seen by every signed-in user, so it stays in the
-- platform database, in schema report_library (owner report_composer_rw, made by the init files). A
-- layout made from one keeps no link to it. source_project_id says where it was saved from: a plain
-- uuid without a foreign key, because the library must never depend on a project (D4).

CREATE TABLE report_library.preset (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name              text NOT NULL UNIQUE CONSTRAINT preset_name_check CHECK (char_length(name) BETWEEN 1 AND 120),
    description       text NOT NULL DEFAULT '',
    language          text CONSTRAINT preset_language_check CHECK (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
    toc               text CONSTRAINT preset_toc_check CHECK (toc IN ('auto', 'on', 'off')),
    numbering         boolean,
    blocks            jsonb NOT NULL CONSTRAINT preset_blocks_check CHECK (jsonb_typeof(blocks) = 'array'),
    source_project_id uuid,
    created_by        text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);
