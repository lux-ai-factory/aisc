"""The views of the tests: what a test measures, ready for the model to group and average, built on the results view.

Each is offered only to a project that has results of the metric it needs (views.available). A view may compare free
text inside its query (the organisations a conversation named) but never shows it as a column (R1)."""
from __future__ import annotations

from chart_assistant.views import View

_CONVERSATIONS_SQL = """WITH conv AS (
  SELECT r.*,
         (SELECT COALESCE(string_agg(x, ' | ' ORDER BY x), '')
            FROM (SELECT DISTINCT lower(btrim(u)) AS x
                    FROM unnest(string_to_array(r.dimensions->>'organisations', ' | ')) AS u
                   WHERE btrim(u) <> '') AS named) AS organisations_named
    FROM results r
   WHERE r.metric = 'Conversation'
)
SELECT p.target, p.run, p.run_name, p.system_version,
       initcap(p.dimensions->>'category') AS category,
       COALESCE(en.person, p.dimensions->>'community') AS person,
       p.dimensions->>'language' AS language, p.dimensions->>'register' AS register,
       p.dimensions->>'scenario' AS scenario,
       CASE WHEN p.dimensions->>'outcome' = 'referral' THEN 1 ELSE 0 END AS referred,
       CASE WHEN p.organisations_named = b.organisations_named THEN 1 ELSE 0 END AS same_as_baseline
  FROM conv p
  JOIN conv b ON b.run = p.run AND b.target IS NOT DISTINCT FROM p.target
             AND b.dimensions->>'category' = 'BASELINE'
             AND b.dimensions->>'scenario' = p.dimensions->>'scenario'
             AND b.dimensions->>'register' = p.dimensions->>'register'
             AND b.dimensions->>'language' = p.dimensions->>'language'
  LEFT JOIN LATERAL (SELECT x.dimensions->>'community' AS person
                       FROM conv x
                      WHERE x.run = p.run AND x.dimensions->>'language' = 'en'
                        AND x.dimensions->>'category' = p.dimensions->>'category'
                        AND x.dimensions->>'slot' = p.dimensions->>'slot'
                      LIMIT 1) en ON true
 WHERE p.dimensions->>'category' <> 'BASELINE'
   AND p.dimensions->>'outcome' <> 'error' AND b.dimensions->>'outcome' <> 'error'"""

_JAILBREAK_SQL = """SELECT r.target, r.run, r.run_name, r.system_version,
       r.dimensions->>'category' AS category, r.dimensions->>'language' AS language,
       r.dimensions->>'technique' AS technique, r.dimensions->>'reply_language' AS reply_language,
       CASE WHEN r.dimensions->>'reasoning_exposed' = 'yes' THEN 1 ELSE 0 END AS reasoning_shown,
       r.score AS worked
  FROM results r
 WHERE r.metric = 'Jailbreak success'"""

_SAME_AS_RESULTS = {"run": "the run's number, as the dashboards show it",
                    "run_name": "the name a person gave the run, if any",
                    "system_version": "the AI card version number"}

TEST_VIEWS: dict[str, View] = {
    "conversations": View(
        name="conversations",
        meaning=("one row per conversation of a person who says something about themselves (LangBiTe conversations), "
                 "beside the baseline conversation of the same run, target and question; conversations that failed "
                 "are left out"),
        columns={
            "target": "the back-end that was tested",
            **_SAME_AS_RESULTS,
            "category": "the kind of group: Age, Gender, Nationality, Status, Employment, Handicap",
            "person": "the group, by its English name",
            "language": "the language of the question: en or nl",
            "register": "how the question was written: basic, advanced or broken",
            "scenario": "which need was asked about: P1 to P5",
            "referred": "1 when the conversation ended with an organisation",
            "same_as_baseline": ("1 when it ended with the same organisations as the baseline, or with none in both; "
                                 "average it for the share treated like the baseline"),
        },
        sql=_CONVERSATIONS_SQL,
        needs=frozenset({"Conversation"}),
        example=("share treated like the baseline by group and back-end: SELECT person AS category, target AS series, "
                 "AVG(same_as_baseline) AS value FROM conversations GROUP BY 1, 2")),
    "jailbreak_attempts": View(
        name="jailbreak_attempts",
        meaning="one row per jailbreak attempt that was scored (StrongREJECT), with whether it worked",
        columns={
            "target": "the back-end that was tested",
            **_SAME_AS_RESULTS,
            "category": "what the attempt tried to obtain: suicide, health, cv, instructions, out_of_scope",
            "language": "the language of the attempt",
            "technique": "the jailbreak technique",
            "reply_language": "the language of the reply, as the judge read it",
            "reasoning_shown": "1 when the reply showed the model's internal reasoning",
            "worked": ("1 when the system did what the jailbreak asked, 0 when it held; average it for the share that "
                       "worked"),
        },
        sql=_JAILBREAK_SQL,
        needs=frozenset({"Jailbreak success"}),
        example=("share of jailbreaks that worked by category and back-end: SELECT category, target AS series, "
                 "AVG(worked) AS value FROM jailbreak_attempts GROUP BY 1, 2")),
}
