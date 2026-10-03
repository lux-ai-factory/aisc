-- Objective ids O1 ... O50: the control objectives are numbered in catalogue order, replacing
-- R1.1 ... R11.4. A stored link is renamed by the table below (a copy of the control-objectives
-- service's data/objective_id_renames.csv); an id the table does not know is left as it is. Only
-- an O id is accepted afterwards: the check is NOT VALID so such a left-over row stays.
-- Safe to run again.
ALTER TABLE evidence.link DROP CONSTRAINT IF EXISTS link_objective_id_check;

UPDATE evidence.link l SET objective_id = r.new_id
  FROM (VALUES
    ('R1.1', 'O1'),
    ('R1.2', 'O2'),
    ('R1.3', 'O3'),
    ('R1.4', 'O4'),
    ('R2.1', 'O5'),
    ('R2.2', 'O6'),
    ('R2.3', 'O7'),
    ('R2.4', 'O8'),
    ('R2.5', 'O9'),
    ('R2.6', 'O10'),
    ('R3.1', 'O11'),
    ('R3.2', 'O12'),
    ('R3.3', 'O13'),
    ('R3.4', 'O14'),
    ('R3.5', 'O15'),
    ('R3.6', 'O16'),
    ('R4.1', 'O17'),
    ('R4.2', 'O18'),
    ('R4.3', 'O19'),
    ('R4.4', 'O20'),
    ('R5.1', 'O21'),
    ('R5.2', 'O22'),
    ('R5.3', 'O23'),
    ('R6.1', 'O24'),
    ('R6.2', 'O25'),
    ('R7.1', 'O26'),
    ('R7.2', 'O27'),
    ('R7.3', 'O28'),
    ('R8.1', 'O29'),
    ('R8.2', 'O30'),
    ('R8.3', 'O31'),
    ('R8.4', 'O32'),
    ('R9.1', 'O33'),
    ('R9.2', 'O34'),
    ('R9.3', 'O35'),
    ('R9.4', 'O36'),
    ('R9.5', 'O37'),
    ('R9.6', 'O38'),
    ('R9.7', 'O39'),
    ('R9.8', 'O40'),
    ('R9.9', 'O41'),
    ('R10.1', 'O42'),
    ('R10.2', 'O43'),
    ('R10.3', 'O44'),
    ('R10.4', 'O45'),
    ('R10.5', 'O46'),
    ('R11.1', 'O47'),
    ('R11.2', 'O48'),
    ('R11.3', 'O49'),
    ('R11.4', 'O50')
  ) AS r (old_id, new_id)
 WHERE l.objective_id = r.old_id;

ALTER TABLE evidence.link ADD CONSTRAINT link_objective_id_check
  CHECK (objective_id ~ '^O[1-9][0-9]*$') NOT VALID;
