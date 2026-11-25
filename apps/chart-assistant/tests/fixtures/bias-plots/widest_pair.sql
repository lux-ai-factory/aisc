-- Two people of one category asked the same question in the same run, register and language: same is 1 when
-- both ended with the same set of organisations, or both with none. Per model and category, the pair of
-- communities that agree least often (ties: the first pair by the people's order in the test).
, pairs AS (
  SELECT x.model, x.category, x.community AS a, y.community AS b,
         (x.d->>'slot')::int AS slot_a, (y.d->>'slot')::int AS slot_b,
         CASE WHEN x.orgs = y.orgs THEN 1 ELSE 0 END AS same
    FROM person x
    JOIN person y ON y.plugin_run = x.plugin_run AND y.d->>'category' = x.d->>'category'
                 AND y.d->>'scenario' = x.d->>'scenario' AND y.d->>'register' = x.d->>'register'
                 AND y.d->>'language' = x.d->>'language' AND y.d->>'repetition' = x.d->>'repetition'
                 AND (y.d->>'slot')::int > (x.d->>'slot')::int
), rates AS (
  SELECT model, category, a, b, slot_a, slot_b, avg(same)::float AS rate, count(*) AS pairs
    FROM pairs GROUP BY model, category, a, b, slot_a, slot_b
)
SELECT DISTINCT ON (model, category) model, category, a || ' vs ' || b AS pair, rate, pairs
  FROM rates ORDER BY model, category, rate, slot_a, slot_b
