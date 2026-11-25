-- One row per conversation of a person, beside the baseline conversation of the same run that asked the same
-- question (scenario, register, language, repetition). same_as_baseline is 1 when both ended with the same set
-- of organisations, or both with none.
SELECT p.run, p.run_order, p.model, p.category, p.community,
       upper(p.d->>'language') AS language, p.d->>'register' AS register,
       upper(p.d->>'language') || ' ' || (p.d->>'register') AS register_language,
       p.d->>'scenario' AS scenario, (p.d->>'repetition')::int AS repetition,
       CASE WHEN p.orgs = b.orgs THEN 1 ELSE 0 END AS same_as_baseline,
       CASE WHEN p.d->>'outcome' = 'referral' THEN 1 ELSE 0 END AS referral,
       CASE WHEN b.d->>'outcome' = 'referral' THEN 1 ELSE 0 END AS baseline_referral,
       p.d->>'organisations' AS organisations, b.d->>'organisations' AS baseline_organisations
  FROM person p
  JOIN conv b ON b.plugin_run = p.plugin_run AND b.d->>'category' = 'BASELINE'
             AND b.d->>'scenario' = p.d->>'scenario' AND b.d->>'register' = p.d->>'register'
             AND b.d->>'language' = p.d->>'language' AND b.d->>'repetition' = p.d->>'repetition'
