-- Objective sets: a project writes its own sets, coded with 2 to 6 capital letters, so a
-- linked objective is the built-in O1 ... O50 or a set's own, like BNK3. NOT VALID as in 0017: an old
-- id left behind stays. Safe to run again.
ALTER TABLE evidence.link DROP CONSTRAINT IF EXISTS link_objective_id_check;

ALTER TABLE evidence.link ADD CONSTRAINT link_objective_id_check
  CHECK (objective_id ~ '^(O|[A-Z]{2,6})[1-9][0-9]*$') NOT VALID;
