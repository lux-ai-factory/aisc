-- Credentials in headers of the connection's own choosing (X-Token and the like): the names are public,
-- the values one Fernet token of a JSON object {name: value}, decrypted only to call the system.
ALTER TABLE connection.endpoint ADD COLUMN IF NOT EXISTS secret_header_names jsonb NOT NULL DEFAULT '[]';
ALTER TABLE connection.endpoint ADD COLUMN IF NOT EXISTS secret_headers_ciphertext text NULL;
