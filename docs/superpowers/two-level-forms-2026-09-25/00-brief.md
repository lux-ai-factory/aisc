# Two-level forms: question sets and questionnaires (product owner brief, 2026-09-25)

Context: `apps/qualification` on `feat/unified-modules` has an uncommitted, deployed "form assembly"
feature (docs in `../form-assembly-2026-09-24/`, 01 to 10). In it one object, a *form*, both authors
questions and is what a card is filled with, and a question's wording lives on each form version that
uses it (copied when picked). The product owner rejected that. This brief is the agreed replacement.

## Decisions (final)

1. **Two levels, these names.**
   - **Question set**: where questions are written. Created in the app or imported. Every question
     belongs to exactly one set. Editing a set creates a new set version. Annex IV is a built-in,
     read-only set. Sets have no blocks.
   - **Questionnaire**: assembled only by picking questions from question-set versions, plus choosing
     blocks (risks, pickers, metadata fields; the identity block name/version/provider is always
     included and locked). It can never create or reword a question. It is what a card is filled
     with. "Use once" is an unlisted questionnaire. The default questionnaire is the built-in
     "Annex IV default" (all 14 Annex IV questions, all blocks), fixed for every project; nobody can
     change which questionnaire is the default.
2. **Pinned only.** A questionnaire version points at specific set versions. It never follows the
   latest automatically. When a referenced set has a newer version whose wording for a picked
   question differs (or the question was removed), the questionnaire shows "update available";
   accepting creates a new questionnaire version.
3. **Cards never change.** A card version renders with the exact wording of the questionnaire
   version it was filled with. Moving a system to a newer questionnaire version creates a new card
   version (existing card versioning); answers carry over by stable question identity; a question
   whose wording changed keeps its answer, flagged for review.
4. **Stable question identity** (`scope`, `local_id`) across set versions; wording, citation,
   required flag and Annex point are per set version.
5. **Nothing used is ever deleted.** Sets and questionnaires can be retired (hidden from pickers,
   still resolvable).
6. **Who and when** recorded on every version (created_by from the signed-in user).
7. **Export / import.**
   - A question set exports/imports as today's CSV and Markdown (round-trip exact, incl. the formula
     guard and escaping already implemented).
   - A questionnaire exports by default as references (set id, set version, scope, local id, plus
     blocks); a "self-contained" option bundles the referenced wording. Importing a self-contained
     file creates a new question set plus a questionnaire; importing a reference file on an install
     lacking the referenced set versions fails with a clear message listing what is missing.
   - Import of a question-set file always creates a question set, optionally also a questionnaire
     with all its questions.
8. **Existing custom forms are split automatically**: its own questions become a question set, the
   form becomes a questionnaire. (Live has none; the rule is still needed.)
9. **Forms are install-wide, never project-scoped** (unchanged). Search, multi-select of sources
   with all questions ticked by default, wide layout, the design pass look: keep them, now in the
   questionnaire builder, selecting question-set versions instead of forms. The "+ New question" and
   "Edit (make a copy)" actions leave the questionnaire builder and live only in the question-set
   editor.
10. **Dockerfile**: replace the image's default `prisma db push --accept-data-loss` with
    `prisma migrate deploy`.

## Database target (agreed)

```
question_set                 id, name, description, origin (builtin|builder|import),
                             retired_at, created_at, created_by
question_set_version         id, set_id, number, created_at, created_by            (append-only)
question                     id, set_id, scope, local_id, created_at               (identity fixed)
question_set_version_item    set_version_id, question_id, position,
                             text, citation, required, annex_point, group_label    (append-only; THE wording)
questionnaire                id, name, description, origin, listed, retired_at, created_at, created_by
questionnaire_version        id, questionnaire_id, number, blocks[], created_at, created_by  (append-only)
questionnaire_version_item   questionnaire_version_id, position, set_version_id, question_id
                             FK (set_version_id, question_id) -> question_set_version_item   (append-only)
qualification.questionnaire_version_id   renamed from form_version_id; NULL = Annex IV default v1
qualification_answer                      unchanged
```

Migration (a new forward migration; 20260925090000 and 20260925120000 are applied on live and must
not be edited):
1. Create the tables; append-only triggers on the four version/item tables (same pattern as today).
2. `form annex-iv-default` becomes question set "Annex IV" v1 (14 wording rows, same question ids)
   and a new built-in questionnaire "Annex IV default" v1 (14 items pointing at set v1, all blocks).
   Move the "one built-in / default is fixed" rules to the questionnaire.
3. Every other form: own questions -> a new set (versions keep their wording); form -> questionnaire
   (same numbers, blocks, listed); each item points at the owning set version whose wording matches
   what was pinned, creating a set version where none matches exactly, so no wording is lost.
4. `qualification.form_version_id` -> `questionnaire_version_id` pointing at the migrated version;
   must not trip the existing "only the latest card changes" triggers.
5. Drop the old form tables in the same transaction, after row-count checks that abort on mismatch.
6. Unchanged and proven unchanged: knowledge graph and its digest, answers, card JSON.

Live DB facts (read-only check, 2026-09-25): 1 form (builtin), 1 form version, 14 questions, 14
version items, 1 card with form_version_id NULL, 14 answers, no copies, no custom forms.

## Process rules for every agent
- Tests are the contract; never weaken or delete tests except where the spec says behaviour changes
  (then minimally, listed with reason).
- No migrate/db push against running DBs; ports 5432/5433 are the live stack; DB tests only via
  `apps/qualification/test/db/throwaway-db.sh`; leave no container behind; do not touch other
  sessions' containers.
- No docker changes other than the Dockerfile line in decision 10; no rebuild/restart/deploy.
- No commits, pushes, stash, reset, checkout, clean, `git add -A` (another session commits on this
  branch).
- Python venvs: create throwaway ones in the session scratchpad
  `/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad/` (earlier ones
  were deleted); the agents suite must run from a scratch cwd because
  `services/agents/application.log` is root-owned (see `../form-assembly-2026-09-24/08-plan-round2.md`
  section 6 for commands). Prefill has its own `.venv`.
- Never use em dashes in prose or UI text.
