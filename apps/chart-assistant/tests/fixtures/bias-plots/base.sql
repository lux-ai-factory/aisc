WITH conv AS (
  -- every "Conversation" result: one conversation of a LangBiTe (Mijke) run, as its conversations.jsonl line says
  SELECT ep.id AS plugin_run, m.dimensions AS d,
         COALESCE(t.label, 'unknown') AS model,
         'Run ' || r.run_number || ' · ' || COALESCE(NULLIF(btrim(ep.name), ''),
             COALESCE(t.label, '') || ' · ' || to_char(e.created_at, 'DD Mon YYYY, HH24:MI')) AS run,
         r.run_number AS run_order,
         -- the organisations named, as a set: trimmed, lower case, sorted, each once
         (SELECT COALESCE(string_agg(x, ' | ' ORDER BY x), '')
            FROM (SELECT DISTINCT lower(btrim(u)) AS x
                    FROM unnest(string_to_array(m.dimensions->>'organisations', ' | ')) AS u
                   WHERE btrim(u) <> '') AS s) AS orgs
    FROM engine.aisc_backend_measurement m
    JOIN engine.aisc_backend_metric met ON met.id = m.metric_id AND met.name = 'Conversation'
    JOIN engine.aisc_backend_observation o ON o.id = m.observation_id
    JOIN engine.aisc_backend_evaluationplugin ep ON ep.id = o.evaluation_plugin_id
    JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id
    JOIN (SELECT id, dense_rank() OVER (ORDER BY created_at, id) AS run_number
            FROM engine.aisc_backend_evaluation) r ON r.id = e.id
    LEFT JOIN engine.aisc_backend_evaluationinput ti ON ti.evaluation_plugin_id = ep.id AND ti.name = 'target'
    LEFT JOIN engine.aisc_backend_aicomponent tc ON tc.id = ti.component_id
    LEFT JOIN target.target t ON t.engine_component = tc.pid
),
person AS (
  -- a person's conversation, the person named as in English (the Dutch question names the same person
  -- by the same slot), the five status sentences by a short name
  SELECT p.*, initcap(p.d->>'category') AS category,
         CASE en.name
           WHEN 'I am a refugee' THEN 'refugee'
           WHEN 'I am an immigrant' THEN 'immigrant'
           WHEN 'I moved to the Netherlands and I am now a Dutch citizen' THEN 'naturalised citizen'
           WHEN 'My parents moved to the Netherlands, I was born here' THEN 'second generation'
           WHEN 'I was born in the Netherlands' THEN 'born in NL'
           ELSE en.name END AS community
    FROM conv p
    LEFT JOIN LATERAL (SELECT x.d->>'community' AS name FROM conv x
                        WHERE x.plugin_run = p.plugin_run AND x.d->>'language' = 'en'
                          AND x.d->>'category' = p.d->>'category' AND x.d->>'slot' = p.d->>'slot'
                        LIMIT 1) en ON true
   WHERE p.d->>'category' <> 'BASELINE'
)
