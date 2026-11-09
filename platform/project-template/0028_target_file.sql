-- A component of the AI card reached by an uploaded file (a model file or a dataset) instead of an
-- endpoint. The bytes live in the engine, on one engine component of the matching type made for the
-- target (file_component); here is what the latest upload was, so the page and the runs can say which
-- file a component is. A replaced file keeps its object in the engine's bucket for the runs that used it.
ALTER TABLE target.target
    ADD COLUMN IF NOT EXISTS file_component   uuid NULL,
    ADD COLUMN IF NOT EXISTS file_name        text NULL CHECK (file_name IS NULL OR length(file_name) BETWEEN 1 AND 255),
    ADD COLUMN IF NOT EXISTS file_size        bigint NULL CHECK (file_size IS NULL OR file_size > 0),
    ADD COLUMN IF NOT EXISTS file_sha256      text NULL CHECK (file_sha256 IS NULL OR file_sha256 ~ '^[0-9a-f]{64}$'),
    ADD COLUMN IF NOT EXISTS file_uploaded_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS file_uploaded_by text NULL;
