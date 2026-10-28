-- A connection's kind is a built-in protocol (openai, rest, a2a, oip) or the name of an adapter installed in
-- the platform's adapters folder (platform_service/adapters.py). The platform checks a kind against the
-- installed adapters when a connection is saved; here only its shape is checked, so an adapter that is
-- removed later leaves its connections readable, editable and deletable.
ALTER TABLE connection.endpoint DROP CONSTRAINT IF EXISTS endpoint_kind_check;
ALTER TABLE connection.endpoint ADD CONSTRAINT endpoint_kind_name CHECK (kind ~ '^[a-z][a-z0-9-]{0,39}$');
