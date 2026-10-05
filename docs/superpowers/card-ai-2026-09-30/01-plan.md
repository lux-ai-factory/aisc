# Card AI and people terms: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The form offers VAIR's terms for the provider, the deployer and the people a risk affects; Refine with AI also proposes short names for long answers and flags places where the card contradicts its own answers.

**Architecture:** Three parts, built in this order because each later part reads what the earlier one adds to the graph. (A) Form: two new vocabularies (AIOperator, AISubject) flow through the generated vocab, the form, the parser, the database, the export, the builder, prefill and the report, exactly the way `systemType` does today. (B) Names: the filler asks the ontology service which nodes carry a long text, drafts one name each, checks them deterministically and publishes them in `extracted.names`, keyed by node and guarded by the text they name. (C) Consistency: one extra filler pass reads the answers and the author's choices and publishes findings with a verbatim quote, which the builder puts on the node as a new flag `inconsistent` with its explanation.

**Tech Stack:** Next.js + Prisma (TypeScript, vitest) in `apps/qualification`; Python services `services/ontology` (rdflib, FastAPI, pytest), `services/agents` (filler, pytest), `services/prefill` (pytest); `apps/report-generator` (Python, pytest).

**Spec:** this conversation, 2026-09-30. User request: "do 1, 2, 4, adapt the form to include the VAIR terms". Items: (1) short names for long answers, (2) consistency review that only flags, (4) VAIR selects for deployer and affected people. Background audit: the filler drafts only `techniques`; nobody supplies `extracted.names`; `schema.py` dropped AISubject by the user's earlier simplification.

## Decisions to confirm before Task 1

| # | Decision | Recommended | Why |
|---|---|---|---|
| D1 | Bring AISubject back into the graph schema (it was dropped by your simplification "affected persons are Users") | **Yes**, as a subclass of Stakeholder, plus `hasAISubject` | Without it VAIR's 19 people terms (Employee, Job Applicant, Natural Person, Asylum Seeker...) have no class to type, and item 4 for affected people cannot be done |
| D2 | The risk row's "Who is affected" becomes ONE select: VAIR's people first, then our "Operator" and "User" only for what VAIR lacks | **Yes** | Your rule: no double dropdown, VAIR first. Old cards keep their `operator` / `user` values, so no data migration |
| D3 | The provider (company) gets the same optional select as the deployer | **Yes** | Same class (AIOperator); VAIR's 17 terms are public bodies, so for a bank both stay empty, which is the normal case |
| D4 | An AI name is shown with a small "AI name" badge until a reviewer edits or confirms it | **Yes** | The author wrote the text; the name is the AI's, and the card must say whose words it shows |

If D1 is "no", drop Task 3's AISubject half, Task 4's affected half and Task 6; the rest stands.

## Global Constraints

- No user-visible "VAIR" anywhere on the form or the card (sweep test in `test/unit/vairFormUi.test.tsx`). The methodology page may say it.
- VAIR has precedence; our own entries only where VAIR has none; one control per field, never two dropdowns for one thing.
- A select is required only where VAIR can always answer. The three new selects are all optional; empty means "none fits".
- The AI never changes what the author typed. It adds names (shown as AI names) and flags (which only point); a reviewer edit settles both.
- `airo/airo.ttl` and `airo/vair.ttl` are the authors' files and are not edited (guard-frozen.sh G3 hashes them).
- Test-first for every change. Do not run prettier on repo files.
- Work in the running clone `~/aisc-fresh-2026-09-30/aisc`. `apps/qualification` is detached at `31c5b1e`: `git checkout feat/unified-modules` there before the first commit (it points at the same commit). Nothing is pushed without naming the repos and getting a yes.
- Label rule: a name is at most 60 characters (`LABEL_MAX` in `services/ontology/airo_min/build.py` and `services/agents/fill/controls.py`).

## Review Focus

1. The author edits a long answer after Refine with AI: the old AI name must not be applied to the new text. Pinned in Task 7 (`test_a_name_for_other_text_is_ignored`).
2. The author deletes or reorders risk rows after a run: node ids shift (`risk1` becomes `risk0`), so a name or a finding keyed by id would land on the wrong risk. Same guard, pinned in Task 7 and Task 10 (`test_a_note_for_other_text_is_ignored`).
3. Cards saved before this change (affected `operator` / `user`, no provider/deployer term) keep building, rendering and printing unchanged. Pinned in Task 4 (`test_old_affected_values_still_link_the_operator_and_user`) and Task 6.
4. The model answers with a node id that does not exist, a quote that is not in the answers, or malformed JSON: those findings are dropped into the run record, the run never crashes and still publishes the techniques. Pinned in Task 11.
5. A document uploaded with "Affected: job applicants" (label, plural, lower case) or with a word that names no term: the first lands on `JobApplicant`, the second is left open, never guessed. Pinned in Task 5.

---

## File map

| File | Change | Part |
|---|---|---|
| `services/ontology/airo_min/schema.py` | AISubject + hasAISubject, SCHEMA_VERSION 1.1 | A |
| `services/ontology/airo_min/vair_vocab.py` | FORM_CLASSES += AIOperator, AISubject | A |
| `src/data/vair_vocab.json` | regenerated | A |
| `src/data/vairVocab.ts` | `OPERATORS`, `SUBJECTS` | A |
| `src/data/airoVocab.ts` | `isAffected` accepts VAIR subjects too | A |
| `prisma/schema.prisma`, `prisma/migrations/20261001000000_people_terms/migration.sql` | `provider_term`, `deployer_term` | A |
| `src/server/forms/QualificationFormParser.ts` | read and check the three picks | A |
| `src/server/repositories/QualificationRepository.ts`, `src/server/services/QualificationExporter.ts`, `src/domain/cardVersions.ts` | carry `providerTerm`, `deployerTerm` | A |
| `src/app/p/[project]/qualify/new/QualifyForm.tsx`, `RiskRows.tsx`, `[id]/AnsweredForm.tsx` | the selects, the answered view | A |
| `services/ontology/airo_min/build.py` | type provider/deployer; AISubject nodes; guarded names; notes | A, B, C |
| `services/ontology/airo_min/view.py`, `patch.py` | `nameDrafted`, `flagNotes`; an edit clears both | B, C |
| `services/prefill/prefill/picks.py`, `risks.py` | read the new lines | A |
| `apps/report-generator/report_renderer/data/vocab.py` | affected label from VAIR too | A |
| `services/agents/fill/names.py` (new), `consistency.py` (new), `workflow.py`, `prompts.py` | the two new passes | B, C |
| `services/agents/prompts/naming-long-answers.md` (new), `checking-consistency.md` (new) | their prompts | B, C |
| `src/domain/OntologyView.ts`, `[id]/NodeChip.tsx`, `[id]/NodeEditor.tsx` | badge, flag text, note | B, C |

## Task 0: test environments

**Files:** none in the repo (venvs are ignored by `.gitignore`; check with `git check-ignore -v services/ontology/.venv`, and if not ignored add `.venv` to `.git/info/exclude` of the submodule).

- [ ] **Step 1: make the venvs**

```bash
cd ~/aisc-fresh-2026-09-30/aisc/apps/qualification
for s in ontology agents prefill; do
  python3 -m venv services/$s/.venv
  services/$s/.venv/bin/pip install -q -r services/$s/requirements.txt pytest
done
```

- [ ] **Step 2: record the baselines** (failures that exist before any change are "known")

```bash
(cd services/ontology && .venv/bin/pytest -q 2>&1 | tail -3)
(cd services/agents && .venv/bin/pytest -q 2>&1 | tail -3)
(cd services/prefill && .venv/bin/pytest -q 2>&1 | tail -3)
npx vitest run test/unit 2>&1 | tail -3
```

Expected: ontology about 322 passed, agents about 188, qualification unit 1591. Write the numbers into `docs/superpowers/card-ai-2026-09-30/02-baseline.md`.

---

## Part A: people terms on the form

### Task 1: the two vocabularies

**Files:**
- Modify: `services/ontology/airo_min/schema.py`, `services/ontology/airo_min/vair_vocab.py`
- Regenerate: `src/data/vair_vocab.json`
- Modify: `src/data/vairVocab.ts`
- Test: `services/ontology/tests/test_schema.py`, `services/ontology/tests/test_vair_vocab.py`, `test/unit/vairVocab.test.ts` (new)

**Interfaces:**
- Produces: `CLASSES["AISubject"] == "Stakeholder"`; `PROPERTIES["hasAISubject"] == (("AISystem",), "AISubject")`; JSON `classes.AIOperator` (17 terms) and `classes.AISubject` (19 terms); TS `OPERATORS: VairTerm[]`, `SUBJECTS: VairTerm[]`, `VairClass` includes both.

- [ ] **Step 1: failing tests**

`services/ontology/tests/test_schema.py`, append:

```python
def test_aisubject_is_back_as_a_stakeholder():
    from airo_min.schema import CLASSES, PROPERTIES, SCHEMA_VERSION
    assert CLASSES["AISubject"] == "Stakeholder"
    assert PROPERTIES["hasAISubject"] == (("AISystem",), "AISubject")
    assert PROPERTIES["hasImpactOnStakeholder"] == (("Impact",), "Stakeholder")
    assert SCHEMA_VERSION == "1.1"
```

`services/ontology/tests/test_vair_vocab.py`, append:

```python
def test_the_form_offers_operators_and_subjects():
    from airo_min.vair_vocab import FORM_CLASSES, vocab
    assert "AIOperator" in FORM_CLASSES and "AISubject" in FORM_CLASSES
    v = vocab()["classes"]
    assert len(v["AIOperator"]) == 17
    assert len(v["AISubject"]) == 19
    assert {"JobApplicant", "Employee", "NaturalPerson"} <= {t["id"] for t in v["AISubject"]}
```

(If the module's builder function is not called `vocab`, use the name `--write` calls; read `vair_vocab.py` first.)

`test/unit/vairVocab.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { OPERATORS, SUBJECTS } from "@/data/vairVocab";

describe("people vocabularies", () => {
  it("offers VAIR's operators and subjects", () => {
    expect(OPERATORS.length).toBe(17);
    expect(SUBJECTS.map((t) => t.id)).toContain("JobApplicant");
  });
});
```

- [ ] **Step 2: run, expect FAIL** (`KeyError: 'AISubject'`, `OPERATORS` undefined)

```bash
(cd services/ontology && .venv/bin/pytest -q tests/test_schema.py tests/test_vair_vocab.py)
npx vitest run test/unit/vairVocab.test.ts
```

- [ ] **Step 3: implement**

`schema.py`: in the docstring replace the line "AISubject and hasAISubject are dropped; affected persons are Users." with "AISubject is kept (2026-10-01) for the people a risk affects, typed by VAIR's 19 subject terms; hasAISubject links them to the system." Add `"AISubject": "Stakeholder",` after `"AIUser"`, add `"hasAISubject": (("AISystem",), "AISubject"),` after `"hasAIUser"`, set `SCHEMA_VERSION = "1.1"`. `tests/test_schema.py` already cross-checks every class and property against `airo.ttl`, so a typo fails there.

`vair_vocab.py`: add to `FORM_CLASSES`, after `"LocalityOfUse"`:

```python
    "AIOperator",  # Provider and deployer
    "AISubject",  # Risk: who is affected
```

Regenerate: `(cd services/ontology && .venv/bin/python -m airo_min.vair_vocab --write)`.

`vairVocab.ts`: add `| "AIOperator" | "AISubject"` to `VairClass`, and:

```ts
export const OPERATORS = vairTerms("AIOperator");
export const SUBJECTS = vairTerms("AISubject");
```

- [ ] **Step 4: run, expect PASS**; then the whole ontology suite (the drift test and `test_vendored.py` must stay green).

- [ ] **Step 5: commit** `The graph keeps AISubject again, and the form gets VAIR's operators and subjects`

### Task 2: parser, database, export

**Files:**
- Create: `prisma/migrations/20261001000000_people_terms/migration.sql`
- Modify: `prisma/schema.prisma`, `src/data/airoVocab.ts`, `src/server/forms/QualificationFormParser.ts`, `src/server/repositories/QualificationRepository.ts`, `src/server/services/QualificationExporter.ts`, `src/domain/cardVersions.ts`
- Test: `test/unit/vairForm.test.ts`, `test/unit/QualificationExporter.test.ts`, `test/db/projectDatabase.db.test.ts` (column check)

**Interfaces:**
- Consumes: `OPERATORS`, `SUBJECTS` (Task 1).
- Produces: parsed and exported `providerTerm: string | null`, `deployerTerm: string | null`; risk `affected: string` which is `"operator" | "user"` or an AISubject id. `isAffected(id)` true for all three kinds.

- [ ] **Step 1: failing tests**, in `test/unit/vairForm.test.ts` inside the parser `describe` (uses the file's own `submittable()` and `parse()`):

```ts
  it("reads the provider's and the deployer's terms, both optional", () => {
    const fd = submittable();
    fd.set("providerTerm", "");
    fd.set("deployerTerm", "EducationalInstitution");
    const p = parse(fd);
    expect(p.providerTerm).toBeNull();
    expect(p.deployerTerm).toBe("EducationalInstitution");
  });

  it("refuses an operator term that is not an operator", () => {
    const fd = submittable();
    fd.set("deployerTerm", "JobApplicant");
    expect(() => parse(fd)).toThrow(/deployer/i);
  });

  it.each(["operator", "user", "JobApplicant"])("takes %s as who is affected", (value) => {
    const fd = submittable();
    fd.set("risk:0:affected", value);
    expect(parse(fd).risks[0].affected).toBe(value);
  });

  it("refuses an affected value that is neither ours nor a subject", () => {
    const fd = submittable();
    fd.set("risk:0:affected", "Police");
    expect(() => parse(fd)).toThrow(/who is affected/);
  });
```

In `test/unit/QualificationExporter.test.ts` (follow its fixture): assert the export carries `providerTerm` and `deployerTerm`, and drops a stored value that is not an AIOperator term (same rule as `systemType`).

- [ ] **Step 2: run, expect FAIL**: `npx vitest run test/unit/vairForm.test.ts test/unit/QualificationExporter.test.ts`

- [ ] **Step 3: implement**

Migration:

```sql
-- The provider's and the deployer's VAIR operator terms (2026-10-01). Optional: VAIR's 17 are public bodies.
ALTER TABLE qualification.qualification ADD COLUMN provider_term text NULL;
ALTER TABLE qualification.qualification ADD COLUMN deployer_term text NULL;
```

`schema.prisma`, next to `systemType`:

```prisma
  providerTerm      String?               @map("provider_term")
  deployerTerm      String?               @map("deployer_term")
```

and in the `QualificationRisk` comment: "`affected` is one of our two ids in airo_vocab.json or a VAIR AISubject local name."

`airoVocab.ts`:

```ts
import { SUBJECTS } from "./vairVocab";
export const isAffected = (id: string) => AFFECTED.some((e) => e.id === id) || SUBJECTS.some((t) => t.id === id);
```

Parser: next to `systemType` (line 134), `const providerTerm = this.term(formData, "providerTerm", "AIOperator", "provider's term");` and the same for `deployerTerm` with "deployer's term"; add both to the returned object and to the parsed type (line 77). Change the risk type at line 37 to `affected: string;`, the message at line 285 to `` `Risk ${n}: who is affected is not one of the listed groups.` `` (it must still match `/who is affected/`), and the cast at line 325 to `affected`. Check that `this.term` accepts the new classes: its class parameter is typed `VairClass`, which Task 1 extended.

Repository, exporter, cardVersions: add `providerTerm` / `deployerTerm` wherever `systemType` appears (the grep `grep -rn systemType src/server src/domain` lists every spot); the exporter filters with the same "is it a term of its class" helper it uses for `systemType`.

- [ ] **Step 4: run, expect PASS**; then `npx vitest run test/unit`, and the db suite if a test database is available (`npm run test:db`, see `package.json`).

- [ ] **Step 5: commit** `The card stores the provider's and the deployer's terms, and who is affected may be a VAIR group`

### Task 3: the form and the answered view

**Files:**
- Modify: `src/app/p/[project]/qualify/new/QualifyForm.tsx`, `src/app/p/[project]/qualify/new/RiskRows.tsx`, `src/app/p/[project]/qualify/[id]/AnsweredForm.tsx`
- Test: `test/unit/vairFormUi.test.tsx`

**Interfaces:**
- Consumes: `OPERATORS`, `SUBJECTS`, `AFFECTED`; form names `providerTerm`, `deployerTerm`, `risk:<i>:affected`.

- [ ] **Step 1: failing tests**, in `test/unit/vairFormUi.test.tsx` (its helpers `select`, `options`):

```tsx
describe("the people", () => {
  it("offers VAIR's operators for the provider and the deployer, both optional", () => {
    render(<QualifyForm project="p" />);
    for (const name of ["providerTerm", "deployerTerm"]) {
      expect(options(name)).toEqual(OPERATORS.map((t) => t.id));
      expect(select(name)!.required).toBe(false);
    }
  });

  it("asks who is affected in one select: VAIR's groups, then ours", () => {
    render(<RiskRows />);
    const groups = [...select("risk:0:affected")!.querySelectorAll("optgroup")];
    expect(groups.map((g) => g.label)).toEqual(["Standard groups", "Other groups"]);
    const ids = (g: Element) => [...g.querySelectorAll("option")].map((o) => o.value);
    expect(ids(groups[0])).toEqual(SUBJECTS.map((t) => t.id));
    expect(ids(groups[1])).toEqual(["operator", "user"]);
  });
});
```

and in the answered-form `describe`, add `providerTerm: null, deployerTerm: "EducationalInstitution"` to `props.metadata`, `affected: "JobApplicant"` to the risk, and expect the text to contain "Educational Institution" and "Job Applicant". The existing "the word VAIR" sweep covers the new controls.

- [ ] **Step 2: run, expect FAIL**: `npx vitest run test/unit/vairFormUi.test.tsx`

- [ ] **Step 3: implement**

`QualifyForm.tsx`: widen `VairSelect`'s `name` to `"systemType" | "purpose" | "providerTerm" | "deployerTerm"` and give it an optional `label` prop (the existing two keep their labels). Render `<VairSelect name="providerTerm" id="providerTerm" terms={OPERATORS} initial={meta?.providerTerm ?? ""} label="Kind of provider" />` directly under the `company` field, and the deployer one ("Kind of deployer") under `intendedDeployers`, each only when its block is on the form (`has("company")`, `has("intendedDeployers")`). Help text for both: "Only public bodies have a term here. Leave it empty for a company."

`RiskRows.tsx` (the `f.kind === "affected"` branch, line 116): replace the flat list with:

```tsx
<optgroup label="Standard groups">
  {SUBJECTS.map((t) => (<option key={t.id} value={t.id} title={t.definition || undefined}>{t.label}</option>))}
</optgroup>
<optgroup label="Other groups">
  {AFFECTED.map((e) => (<option key={e.id} value={e.id}>{e.label}</option>))}
</optgroup>
```

`AnsweredForm.tsx`: show the two operator terms by label beside company and deployers (`vairLabel("AIOperator", ...)`), and the affected value by `vairLabel("AISubject", id)` when it is a subject, else by `vocabLabel(AFFECTED, id)`.

- [ ] **Step 4: run, expect PASS**; then `npx vitest run test/unit`.

- [ ] **Step 5: commit** `The form asks the kind of provider and deployer, and who is affected from VAIR's groups first`

### Task 4: the builder

**Files:**
- Modify: `services/ontology/airo_min/build.py`
- Test: `services/ontology/tests/test_vair_form.py`

**Interfaces:**
- Consumes: export fields `providerTerm`, `deployerTerm`, risk `affected` (Task 2).
- Produces: `ex.provider` / `ex.deployer` typed with their term; one shared node `ex["subject_<Term>"]` of class AISubject per subject term, linked `system hasAISubject` and `impact hasImpactOnStakeholder`.

- [ ] **Step 1: failing tests** (use the file's existing qualification fixture helper; read it first):

```python
def test_provider_and_deployer_take_their_terms(q):
    q = {**q, "providerTerm": None, "deployerTerm": "EducationalInstitution"}
    g = build_graph(q, {})
    assert (EX.deployer, RDF.type, VAIR.EducationalInstitution) in g
    assert not any(str(o).startswith(str(VAIR)) for o in g.objects(EX.provider, RDF.type))

def test_a_subject_is_one_shared_node_the_impact_points_at(q):
    rows = [{**q["risks"][0], "position": 0, "affected": "JobApplicant"},
            {**q["risks"][0], "position": 1, "affected": "JobApplicant"}]
    g = build_graph({**q, "risks": rows}, {})
    subject = EX["subject_JobApplicant"]
    assert (subject, RDF.type, AIRO.AISubject) in g
    assert (subject, RDF.type, VAIR.JobApplicant) in g
    assert (EX.system, AIRO.hasAISubject, subject) in g
    assert (EX.risk0_impact, AIRO.hasImpactOnStakeholder, subject) in g
    assert (EX.risk1_impact, AIRO.hasImpactOnStakeholder, subject) in g

def test_old_affected_values_still_link_the_operator_and_user(q):
    g = build_graph({**q, "risks": [{**q["risks"][0], "position": 0, "affected": "user"}]}, {})
    assert (EX.risk0_impact, AIRO.hasImpactOnStakeholder, EX.users) in g
```

(`EX` is the card's namespace as the file's other tests build it.)

- [ ] **Step 2: run, expect FAIL**: `(cd services/ontology && .venv/bin/pytest -q tests/test_vair_form.py)`

- [ ] **Step 3: implement**

Provider and deployer: keep the `named(...)` calls, bind each to a variable, and call `_typed(g, provider, qualification.get("providerTerm"))` / `_typed(g, deployer, qualification.get("deployerTerm"))`.

In `_add_risk`, replace the `_AFFECTED_CLASS` guard and the stakeholder lookup with:

```python
    affected = row["affected"]
    if affected in _AFFECTED_CLASS:
        stakeholder = next(iter(g.objects(system, URIRef(AIRO + _AFFECTED_CLASS[affected]))), None)
    elif is_term_for(affected, "AISubject"):
        stakeholder = ex[f"subject_{affected}"]
        if (stakeholder, RDF.type, None) not in g:
            stakeholder = named(g, stakeholder, "AISubject", label_of(affected))
            _typed(g, stakeholder, affected)
            link(g, system, "hasAISubject", stakeholder)
    else:
        raise ValueError(f"unknown affected value: {affected!r} (expected operator, user or a VAIR subject)")
```

and link the impact to `stakeholder` when it is not `None`, as today. `is_term_for` is in `airo_min/vair_terms.py`; `label_of` is already imported for areas.

- [ ] **Step 4: run, expect PASS**; the whole ontology suite (`test_validate.py` checks every node's class and range against the schema).

- [ ] **Step 5: commit** `The graph types the provider and deployer, and names the people a risk affects`

### Task 5: upload fills the new picks

**Files:**
- Modify: `services/prefill/prefill/picks.py`, `services/prefill/prefill/risks.py`
- Test: `services/prefill/tests/test_picks.py`, `services/prefill/tests/test_risks.py` (use the existing file names; `ls services/prefill/tests`)

**Interfaces:**
- Produces: picks `providerTerm`, `deployerTerm` from lines "Provider term:" / "Kind of provider:" and "Deployer term:" / "Kind of deployer:"; risk `affected` matched against our two ids and the AISubject ids and labels.

- [ ] **Step 1: failing tests**

```python
def test_a_document_names_the_deployer_kind():
    picks = read_picks("Kind of deployer: Educational Institution\n")
    assert picks["deployerTerm"] == "EducationalInstitution"

def test_an_unknown_deployer_kind_is_left_open():
    assert "deployerTerm" not in read_picks("Kind of deployer: Retail bank\n")

@pytest.mark.parametrize("text, expected", [
    ("job applicants", "JobApplicant"), ("Job Applicant", "JobApplicant"),
    ("user", "user"), ("the operator", "operator"), ("shareholders", None)])
def test_who_is_affected(text, expected):
    assert affected_of(text) == expected
```

(`read_picks` / `affected_of` stand for the modules' public entry points; use the names the existing tests import, e.g. `picks.picks_of` and `risks._affected`.)

- [ ] **Step 2: run, expect FAIL**: `(cd services/prefill && .venv/bin/pytest -q)`

- [ ] **Step 3: implement**: add to the field map in `picks.py` (line 26 table):

```python
    "providerTerm": ("AIOperator", False, ("provider term", "kind of provider")),
    "deployerTerm": ("AIOperator", False, ("deployer term", "kind of deployer")),
```

In `risks.py` `_affected`: try our two ids first (as today), then match the value against the AISubject ids and labels with the same matcher `prefill.vair` uses for terms (plural "s" stripped, case folded); no match returns the current "left open" value.

- [ ] **Step 4: run, expect PASS**.

- [ ] **Step 5: commit** `Upload reads the kind of provider and deployer, and VAIR's groups for who is affected`

### Task 6: the report names the new groups

**Files:**
- Modify: `apps/report-generator/report_renderer/data/vocab.py`
- Test: its existing vocab test (`grep -rln "affected" apps/report-generator/tests`)

- [ ] **Step 1: failing test**: with `REPORT_VAIR_VOCAB_PATH` pointing at a fixture holding `classes.AISubject = [{"id": "JobApplicant", "label": "Job Applicant"}]`, `vocab["affected"]["JobApplicant"] == "Job Applicant"`, and `vocab["affected"]["user"]` is still our label.
- [ ] **Step 2: run, expect FAIL**.
- [ ] **Step 3: implement**: in `vocab.py`, after building `affected` from `airo_vocab.json`, merge `{t["id"]: t["label"] for t in vair["classes"].get("AISubject", [])}` when the VAIR vocab is available (it is optional: `REPORT_VAIR_VOCAB_PATH`).
- [ ] **Step 4: run, expect PASS**; the report's golden tests stay unchanged (the MCAS fixture uses `user`).
- [ ] **Step 5: commit** (report-generator repo) `The report names a VAIR group of affected people by its label`

---

## Part B: short names from Refine with AI

### Task 7: the builder applies names only to the text they were written for

**Files:**
- Modify: `services/ontology/airo_min/build.py` (`named`, the `names` read at line 196), `services/ontology/airo_min/view.py`, `services/ontology/airo_min/patch.py`
- Test: `services/ontology/tests/test_build.py`

**Interfaces:**
- Produces: `extracted.names` entries may be `{"name": str, "of": str}` (new) or `str` (old, still accepted as before). A `{name, of}` entry applies only when `" ".join(of.split()) == " ".join(text.split())`. An applied entry marks the node `qual:nameDrafted true`; the view exposes `"nameDrafted": true`; a reviewer patch with a `label` removes it.

- [ ] **Step 1: failing tests**

```python
LONG = "Assess the creditworthiness of consumer loan applicants for retail banks in Germany, France and the Netherlands"

def test_a_name_for_this_text_is_used_and_marked():
    q = {**_qualification(), "targetUseCase": LONG}
    g = build_graph(q, {"names": {"purpose": {"name": "Consumer credit assessment", "of": LONG}}})
    assert str(g.value(EX.purpose, RDFS.label)) == "Consumer credit assessment"
    assert g.value(EX.purpose, QUAL.nameDrafted) is not None
    assert str(g.value(EX.purpose, QUAL.fullLabel)) == LONG

def test_a_name_for_other_text_is_ignored():
    q = {**_qualification(), "targetUseCase": LONG + " and Belgium"}
    g = build_graph(q, {"names": {"purpose": {"name": "Consumer credit assessment", "of": LONG}}})
    assert str(g.value(EX.purpose, RDFS.label)).endswith("...")
    assert g.value(EX.purpose, QUAL.nameDrafted) is None

def test_a_reviewed_label_is_no_longer_an_ai_name():
    q = {**_qualification(), "targetUseCase": LONG}
    g = build_graph(q, {"names": {"purpose": {"name": "Consumer credit assessment", "of": LONG}}},
                    patch={"purpose": {"label": "Credit scoring"}})
    assert g.value(EX.purpose, QUAL.nameDrafted) is None
```

(Check `build_graph`'s real signature for the patch argument; `_qualification()` is the file's fixture.)

- [ ] **Step 2: run, expect FAIL**.

- [ ] **Step 3: implement**: in `build_graph`, replace `names: dict[str, str] = dict(extracted.get("names") or {})` with a helper that keeps the raw entries, and give `named` the text check:

```python
def _name_for(entry: Any, text: str) -> tuple[str | None, bool]:
    """A curated name, and whether an agent drafted it. A drafted name carries the text it
    was written for, and names nothing once that text changed (or moved to another row)."""
    if isinstance(entry, str):
        return entry or None, False
    if isinstance(entry, dict) and " ".join(str(entry.get("of", "")).split()) == " ".join(text.split()):
        return entry.get("name") or None, True
    return None, False
```

`named(g, iri, cls, text, name=None)` keeps its signature but `name` may now be the raw entry: call `name, drafted = _name_for(name, text)` first, and when `drafted` add `(node, QUAL.nameDrafted, Literal(True))`. `view.py`: in the per-node loop, `if g.value(node, QUAL.nameDrafted) is not None: out["nameDrafted"] = True`. `patch.py`: where a `label` change is applied, also `g.remove((node, QUAL.nameDrafted, None))`.

- [ ] **Step 4: run, expect PASS**; whole ontology suite (old string names in `examples/mcas.extracted.json` must build as before).

- [ ] **Step 5: commit** `A drafted name applies only to the text it was written for, and says it is drafted`

### Task 8: the filler drafts the names

**Files:**
- Create: `services/agents/fill/names.py`, `services/agents/prompts/naming-long-answers.md`
- Modify: `services/agents/fill/workflow.py` (`FillRun.publish_all`, `run_fill`), `services/agents/fill/prompts.py`
- Test: `services/agents/tests/test_names.py` (new)

**Interfaces:**
- Consumes: `clients.build(qualification, extracted) -> {"view": {"nodes": [...]}, ...}`; each view node has `id`, `cls`, `label`, `fullText`, `provenance`.
- Produces:
  - `nameable(view: dict) -> dict[str, str]`: node id to full text, for nodes with `fullText` set, `provenance == "form"`, and `cls` not in `{"AITechnique", "AIComponent"}`.
  - `draft_names(texts: dict[str, str], complete: Callable[..., str], max_rounds: int = 3) -> tuple[dict[str, dict], list[dict]]`: returns `names` (`{id: {"name", "of"}}`) and the entries it gave up on (`[{"node", "reason"}]`).
  - `run_fill` gains a `build: Callable[[dict, dict], dict]` parameter (default `clients.build`) and publishes `payload["names"]`.

- [ ] **Step 1: failing tests**

```python
from fill.names import draft_names, nameable

VIEW = {"view": {"nodes": [
    {"id": "purpose", "cls": "Purpose", "label": "Assess the...", "fullText": "Assess the creditworthiness of consumer loan applicants for retail banks", "provenance": "form"},
    {"id": "system", "cls": "AISystem", "label": "MCAS 1", "fullText": None, "provenance": "form"},
    {"id": "technique0", "cls": "AITechnique", "label": "x", "fullText": "long long", "provenance": "extracted"},
]}}

def test_only_long_form_texts_are_named():
    assert nameable(VIEW["view"]) == {"purpose": VIEW["view"]["nodes"][0]["fullText"]}

def test_a_good_name_is_kept_with_its_text():
    text = VIEW["view"]["nodes"][0]["fullText"]
    names, gave_up = draft_names({"purpose": text}, lambda *a, **k: '{"purpose": "Consumer loan creditworthiness"}')
    assert names == {"purpose": {"name": "Consumer loan creditworthiness", "of": text}}
    assert gave_up == []

def test_a_name_not_taken_from_its_text_is_asked_again_then_dropped():
    calls = []
    def complete(*a, **k):
        calls.append(1)
        return '{"purpose": "Mortgage fraud detection"}'
    names, gave_up = draft_names({"purpose": "Assess the creditworthiness of consumer loan applicants"}, complete, max_rounds=2)
    assert names == {} and len(calls) == 2
    assert gave_up[0]["node"] == "purpose"

def test_malformed_json_names_nothing():
    names, gave_up = draft_names({"purpose": "Assess the creditworthiness of applicants"}, lambda *a, **k: "sure! here")
    assert names == {} and gave_up
```

plus, in `test_workflow.py`, one test that `run_fill(..., build=lambda q, e: VIEW)` publishes a payload with `"names"` next to `"techniques"`.

- [ ] **Step 2: run, expect FAIL**: `(cd services/agents && .venv/bin/pytest -q tests/test_names.py tests/test_workflow.py)`

- [ ] **Step 3: implement**

`names.py`: `nameable` as specified. `draft_names`: build the user prompt (a numbered list `id: text`), call `complete(system, user)` (read `fill/agents.py` for the exact call shape the writer uses and copy it), parse JSON with `json.loads` inside `try`; for each returned id that is in `texts`, check the name with the existing controls: reuse `controls._labels` and `controls._grounding` by wrapping the name in a one-node `Draft` and passing the node's own text as the source. Keep the ones with no finding; re-ask only for the rest, with the findings' `detail` lines, until `max_rounds`; what is still failing goes to `gave_up`.

`naming-long-answers.md` (front matter like the other prompts):

```markdown
# Naming long answers

Each line is a node of an AI card and the full text its author wrote for it. Give each one a
name: a noun phrase of at most 60 characters, taken from the text's own words, that a person
would recognise as this text. A name names; it does not describe, explain or add anything the
text does not say. The full text stays on the node, so nothing is lost by leaving detail out.

Answer with JSON only, one entry per id you were given: {"<id>": "<name>"}.
```

`prompts.py`: `def naming_prompt(texts, findings=()) -> tuple[str, str]` using `prompt_text("naming-long-answers")`.

`workflow.py`: in `publish_all`, before publishing: `view = self.build(self.qualification, {})["view"]`, then `names, gave_up = draft_names(nameable(view), self.complete)`, then `self.payload["names"] = names` and, when `gave_up`, `self.payload["record"]["names_left"] = gave_up`. Add `build` as a `FillRun` field. A `ServiceError` from `build` is caught: the run publishes without names and records `{"names": "ontology unreachable"}`.

- [ ] **Step 4: run, expect PASS**; the whole agents suite.

- [ ] **Step 5: commit** `Refine with AI names the long answers, from their own words`

### Task 9: the card shows an AI name as one

**Files:**
- Modify: `src/domain/OntologyView.ts`, `src/app/p/[project]/qualify/[id]/NodeChip.tsx`, `src/app/p/[project]/qualify/[id]/NodeEditor.tsx`
- Test: `test/unit/NodeChip.test.tsx`

- [ ] **Step 1: failing test**

```tsx
it("marks a drafted name, and shows the author's text on hover", () => {
  render(<NodeChip node={{ id: "purpose", label: "Consumer credit", cls: "Purpose", vair: null,
                           provenance: "form", nameDrafted: true, fullText: "Assess the creditworthiness..." }}
                   vocabularies={{}} onEdit={() => {}} />);
  expect(screen.getByText("AI name")).toBeTruthy();
  expect(screen.getByRole("button").getAttribute("title")).toBe("Assess the creditworthiness...");
});
```

- [ ] **Step 2: run, expect FAIL**.
- [ ] **Step 3: implement**: `nameDrafted?: boolean` on `OntologyNode`; in `NodeChip`, `{node.nameDrafted && <span className="onto-badge onto-badge--extracted">AI name</span>}`; in `NodeEditor`, when `nameDrafted`, a line above the label field: "This name was proposed by the AI from the text below. Saving the label, even unchanged, makes it yours."
- [ ] **Step 4: run, expect PASS**; `npx vitest run test/unit`.
- [ ] **Step 5: commit** `The card marks an AI name until a person keeps it`

---

## Part C: the consistency review

### Task 10: findings with their reason on the node

**Files:**
- Modify: `services/ontology/airo_min/build.py` (`REVIEW_FLAGS`, a new `notes` read after the flags loop), `services/ontology/airo_min/view.py`, `services/ontology/airo_min/patch.py`
- Test: `services/ontology/tests/test_build.py`, `services/ontology/tests/test_view.py`

**Interfaces:**
- Produces: `REVIEW_FLAGS` includes `"inconsistent"`. `extracted.notes`: `{node_id: [{"why": str, "quote": str, "of": str}]}`, where `of` is the node's label or full text when the note was written. Each applied note adds flag `inconsistent` and a `qual:flagNote` literal `"<why> | <quote>"`. The view exposes `"flagNotes": [{"why", "quote"}]`. A reviewer patch removes flags and notes alike.

- [ ] **Step 1: failing tests**

```python
def test_a_note_rides_on_its_node():
    q = _qualification()
    note = {"why": "the answer names a hosted LLM", "quote": "a hosted third-party LLM", "of": q["risks"][0]["control"]}
    g = build_graph(q, {"notes": {"risk0_control": [note]}})
    assert (EX.risk0_control, QUAL.reviewFlag, Literal("inconsistent")) in g
    view = build_view(g)
    node = next(n for n in view["nodes"] if n["id"] == "risk0_control")
    assert node["flagNotes"] == [{"why": note["why"], "quote": note["quote"]}]

def test_a_note_for_other_text_is_ignored():
    q = _qualification()
    note = {"why": "w", "quote": "q", "of": "a control that is no longer there"}
    g = build_graph(q, {"notes": {"risk0_control": [note]}})
    assert (EX.risk0_control, QUAL.reviewFlag, None) not in g
```

(`build_view` returns the node list under the key the file's other tests read; adjust the lookup to match.)

- [ ] **Step 2: run, expect FAIL**.
- [ ] **Step 3: implement**: add `"inconsistent"` to `REVIEW_FLAGS` and to its comment ("inconsistent: the card's own answers say otherwise, quoted"). After the flags loop:

```python
    for node_id, notes in (extracted.get("notes") or {}).items():
        node = ex[node_id]
        if (node, RDF.type, None) not in g:
            continue
        shown = {" ".join(str(v).split()) for v in (g.value(node, RDFS.label), g.value(node, QUAL.fullLabel)) if v}
        for note in notes:
            if " ".join(str(note.get("of", "")).split()) not in shown:
                continue  # written for another text, or another row now at this position
            g.add((node, QUAL.reviewFlag, Literal("inconsistent")))
            g.add((node, QUAL.flagNote, Literal(f"{note['why']} | {note['quote']}")))
```

`view.py`: `flagNotes` from `qual:flagNote`, split on the first `" | "`, sorted. `patch.py`: next to `g.remove((node, QUAL.reviewFlag, None))`, `g.remove((node, QUAL.flagNote, None))`.

- [ ] **Step 4: run, expect PASS**; whole ontology suite.
- [ ] **Step 5: commit** `A finding carries its reason and its quote to the node, and only to the text it was about`

### Task 11: the filler's consistency pass

**Files:**
- Create: `services/agents/fill/consistency.py`, `services/agents/prompts/checking-consistency.md`
- Modify: `services/agents/fill/workflow.py`, `services/agents/fill/prompts.py`
- Test: `services/agents/tests/test_consistency.py` (new)

**Interfaces:**
- Consumes: the built view (Task 8's `build` call, after names), `qualification["answers"]` (each with `answer` and `annexPoint`).
- Produces: `check(view: dict, answers: list[dict], complete) -> tuple[dict[str, list[dict]], list[dict]]` returning `notes` (Task 10 shape) and the dropped findings. Constants: `MAX_NOTES = 8`, `CHECKED = {"AISystem", "Purpose", "AICapability", "Domain", "Modality", "LocalityOfUse", "AIComponent", "AIModel", "Data", "AIOperator", "AISubject", "RiskSource", "Consequence", "Impact", "RiskControl", "AreaOfImpact"}`.

- [ ] **Step 1: failing tests**

```python
from fill.consistency import check

ANSWERS = [{"annexPoint": "2a", "answer": "The explanation module wraps a hosted third-party LLM, used as-is."}]
VIEW = {"nodes": [{"id": "component-abc", "cls": "AIComponent", "label": "Explanation service",
                   "vair": "ApplicationPlatform", "provenance": "form", "fullText": None}]}

def reply(obj):
    import json
    return lambda *a, **k: json.dumps(obj)

def test_a_quoted_finding_on_a_real_node_is_kept():
    notes, dropped = check(VIEW, ANSWERS, reply({"findings": [
        {"node": "component-abc", "why": "the answer says it wraps an LLM", "quote": "wraps a hosted third-party LLM"}]}))
    assert notes == {"component-abc": [{"why": "the answer says it wraps an LLM",
                                        "quote": "wraps a hosted third-party LLM", "of": "Explanation service"}]}
    assert dropped == []

def test_a_quote_not_in_the_answers_is_dropped():
    notes, dropped = check(VIEW, ANSWERS, reply({"findings": [{"node": "component-abc", "why": "w", "quote": "a fine-tuned model"}]}))
    assert notes == {} and dropped[0]["reason"] == "quote not in the answers"

def test_an_unknown_node_is_dropped():
    notes, dropped = check(VIEW, ANSWERS, reply({"findings": [{"node": "component-zzz", "why": "w", "quote": "hosted third-party LLM"}]}))
    assert notes == {} and dropped[0]["reason"] == "no such node"

def test_garbage_is_no_finding_and_no_crash():
    assert check(VIEW, ANSWERS, lambda *a, **k: "no json")[0] == {}

def test_at_most_eight_and_one_per_node():
    many = [{"node": "component-abc", "why": str(i), "quote": "hosted third-party LLM"} for i in range(12)]
    notes, _ = check(VIEW, ANSWERS, reply({"findings": many}))
    assert len(notes["component-abc"]) == 1
```

plus a workflow test: with a fake `complete` that answers the three prompts in turn, the published payload has `techniques`, `names` and `notes`, and a `ServiceError` from `build` still publishes the techniques.

- [ ] **Step 2: run, expect FAIL**.
- [ ] **Step 3: implement**

`consistency.py`: pick the nodes with `provenance == "form"` and `cls in CHECKED`; the user prompt lists them as `id | class | label | term | full text` and the answers as `[annex point] answer`. One call, no revision rounds (it adds no content, so there is nothing to revise). Parse with `try/json.loads`; keep a finding when its `node` is one of the listed ids, its `quote` (whitespace-normalised, case kept) is a substring of some answer, and its node has none yet; stop at `MAX_NOTES`. `of` is the node's `fullText` or else its `label`. Everything else goes to `dropped` with reason `"no such node"`, `"quote not in the answers"` or `"one per node"`.

`checking-consistency.md`:

```markdown
# Checking an AI card against its own answers

You get the choices an author made on an AI card (each node: its class, its name, its term) and
the answers they wrote. Your only job is to point at a choice that the answers contradict, or
that the answers clearly say is incomplete, so a person can look at it. You change nothing.

Raise a finding only when you can quote the answer: copy a short span of it exactly, character
for character. A finding you cannot quote is not raised. Do not raise style, wording, a term you
would have picked differently when the chosen one is defensible, or anything about a node that
is not listed. At most one finding per node.

Answer with JSON only:
{"findings": [{"node": "<id>", "why": "<one sentence, plain words>", "quote": "<exact span>"}]}
{"findings": []} when the card agrees with its answers.
```

`workflow.py`, in `publish_all` after the names: `view = self.build(self.qualification, {"names": names})["view"]`, `notes, dropped = check(view, self.qualification.get("answers", []), self.complete)`, `self.payload["notes"] = notes`, `self.payload["record"]["notes"] = sum(len(v) for v in notes.values())`, and `self.payload["record"]["notes_dropped"] = dropped` when not empty.

- [ ] **Step 4: run, expect PASS**; whole agents suite.
- [ ] **Step 5: commit** `Refine with AI points at choices the card's own answers contradict, with the quote`

### Task 12: the card shows the finding

**Files:**
- Modify: `src/domain/OntologyView.ts`, `src/app/p/[project]/qualify/[id]/NodeChip.tsx`, `src/app/p/[project]/qualify/[id]/NodeEditor.tsx`, `src/app/p/[project]/qualify/[id]/FillStatus.tsx`
- Test: `test/unit/NodeChip.test.tsx`, `test/unit/FillStatus.test.tsx`

- [ ] **Step 1: failing tests**: a node with `flags: ["inconsistent"]` and `flagNotes: [{why: "the answer says it wraps an LLM", quote: "wraps a hosted third-party LLM"}]` renders the chip text "check" (not the raw flag) and the editor shows the why and the quote in quotation marks; `FillStatus` with a record `{notes: 2}` says "2 places to check".
- [ ] **Step 2: run, expect FAIL**.
- [ ] **Step 3: implement**: `flagNotes?: { why: string; quote: string }[]` on `OntologyNode`; a display map in `NodeChip` `{ inconsistent: "check" }` falling back to the flag itself; `NodeEditor` lists the notes under a heading "Why the AI points here"; the filler's record gets `notes: <count>` (set in Task 11's `publish_all`) and `FillStatus` prints it.
- [ ] **Step 4: run, expect PASS**; `npx vitest run test/unit` (the no-VAIR sweep included).
- [ ] **Step 5: commit** `The card says why the AI points at a choice`

---

## Task 13: deploy and check live

- [ ] **Step 1**: apply the migration and rebuild what changed:

```bash
cd ~/aisc-fresh-2026-09-30/aisc
C="docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml -f docker-compose-infra.development.yml -f docker-compose.development.yml"
$C up -d --build --no-deps qualification-migrate qualification-web qualification-ontology qualification-prefill qualification-agents report-renderer
docker logs qualification-migrate 2>&1 | tail -3   # expect 20261001000000_people_terms applied
```

- [ ] **Step 2**: the person checks, in the browser (reload the page first): the new selects on the form, one upload of the MCAS document, Refine with AI on the MCAS card, the AI names and any "check" chips on the card, one risk with a VAIR group of affected people in the PDF report.
- [ ] **Step 3**: write `docs/superpowers/card-ai-2026-09-30/03-report.md`: suites before and after, what the live run produced (names, notes, dropped), anything that surprised.

## Not in this plan

- Trimming the writer's techniques prompt and removing the unused `components` / `risk_types` properties (audited 2026-09-30, still waiting for a yes).
- Separating "none fits" from "not answered" on the optional selects (item 3 of the 2026-09-30 list, not chosen).
- The report showing the provider's and deployer's kind (only the affected label is added, Task 6).
