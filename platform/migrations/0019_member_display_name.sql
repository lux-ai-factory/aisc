-- A member's display name, as the identity provider gives it (Keycloak's name, else the user name, else the email),
-- kept from the last time the person used the work pages. The work board's Give-to list names members by it, so a
-- person has one name everywhere a part, a doer or a sign-off names them. Never what a decision reads; NULL until
-- the person signs in, when the list falls back to the email, then the subject.
ALTER TABLE core.project_member ADD COLUMN IF NOT EXISTS name text;
