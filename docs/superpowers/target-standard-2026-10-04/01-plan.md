# One standard way for every plugin to reach what it assesses (2026-10-04)

Status: plan, for the user's decisions (section 9). P1 is built (aisc 755217f, local).

## 1. Why

Every plugin today finds the system it assesses its own way: a model list and an API key in its
form, its own environment variables, its own client. None uses the connector the plugin contract
already has (`@system_under_test`, `connections.EndpointClient`). So the endpoint registered in
Manage is used by no plugin, a judge model can be sent to the system under test by accident, and
every plugin has to be learnt separately. The goal is one rule for all plugins: the evaluation picks
the target, the target's endpoint comes from Manage, the plugin's own models are tool settings.

## 2. Terms

| Term | Meaning | Where it is set |
|---|---|---|
| **Target** | what an evaluation assesses: the AI system, or one component of its AI card (the chat assistant, the scoring model, the training data) | the evaluation's target dropdown (one per evaluation) |
| **Endpoint** | how a target is reached: a connection (REST, OpenAI-compatible, A2A, OIP) with its address and key | Manage, Targets and endpoints (one endpoint per target) |
| **Tool model** | a model the plugin uses for its own work: a judge (LLM-as-a-judge), an attacker, a grader, embeddings | the plugin's form on the execution page |
| **Inputs** | files the plugin reads: datasets, ONNX models, prompt templates | the evaluation's input fields (uploaded datasets and models) |

## 3. The rules

- **R1. Every plugin declares how it gets what it assesses**, one of:
  - `@system_under_test(...)`: it calls a live target, reached only through the target's endpoint;
  - `@assesses_inputs()` (new, section 4.2): it only reads its inputs;
  - `@dataset_through_target(...)` (new, section 4.3): it reads a dataset that is first sent, row by
    row, through the target's endpoint.

  A plugin with none of these fails the conformance check (section 7).
- **R2. The target is never set in the plugin's form.** With a target bound, its address, key and
  model come from the platform for the length of the run, written into the plugin's own target
  fields or into variables named for the target (`AISC_TARGET_*`), never into variables a tool model
  also reads (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `API_KEY_OPENAI` and the like).
- **R3. Every tool model has its own explicit fields** on the execution page (model, key, and
  address where it makes sense) and never falls back to a shared environment variable. A plugin
  with no tool model has none.
- **R4. What a plugin cannot do with a target is said before it runs.** A target without an endpoint,
  a protocol the plugin doesn't speak, or a capability the endpoint lacks (tool calls, logprobs) is a
  refusal at the start with the reason, never a failure half-way.
- **R5. The run records what it reached.** The connection, the target and the protocol are saved with
  the run (the decorator's `connection-<name>.json` artifact today), so results say what was assessed.

## 4. The pieces

### 4.1 Done: the dropdown says which targets can be reached (P1, aisc 755217f)

The evaluation form lists every target (inputs-only plugins need targets without an endpoint), and
each name now ends in "· endpoint: <name>" or "· no endpoint". Binding or removing an endpoint in
Manage renames the targets at once. A plugin that requires an endpoint refuses a target without one:
"<target> has no endpoint: set one under Manage, Targets and endpoints". Sean's webapp is unchanged.

### 4.2 The declarations (plugin-interface)

- `@assesses_inputs()`: a class marker, nothing at run time. The conformance check reads it.
- `@system_under_test(...)` (exists): add a class attribute listing the capabilities the plugin needs
  (`needs=("tools",)`, `needs=("logprobs",)`), checked against the endpoint at the start (R4). The
  platform's OpenAI facade carries text messages only, so a plugin that needs tools or logprobs from
  a non-OpenAI endpoint is refused with that reason.
- README of plugin-interface: a section "How a plugin reaches its target" with the three
  declarations, the rules, and one worked example per kind.

### 4.3 New: a dataset through the target (plugin-interface)

`@dataset_through_target(dataset="evaluated-dataset", into=("score", "recommendation"))`: before
`evaluate`, each row of the named dataset input is sent to the target's endpoint as the request body
(a REST endpoint whose body template is `{{input}}` takes the row as it is), and the answer's fields
are added as columns. The plugin then reads the enriched dataset like any upload. Settings on the
execution page: which columns to send (default all), how many calls at once (default 1), a row limit.
Each call goes through the platform (run key, allow-list, ledger) like any other target call; the
answers are saved with the run as an artifact, so the analysis can be re-run without calling again.
First users: data drift (score drift on the MCAS scorer); then fairness and performance, which
today need an uploaded ONNX model and would also accept a predictions column (to be checked per
plugin, P6).

### 4.4 The conformance check (scripts/verify-plugins.sh, check P5)

For every plugin class on the stack's index: exactly one declaration from R1 (FAIL otherwise); for
`@system_under_test`, no tool-model field shares an environment variable with the target mapping
(FAIL); every tool model has explicit fields (WARN when it reads a shared variable). Run with the
other checks by `verify.sh --stack`, so a fresh clone proves it before a workshop.

## 5. Per plugin (from the survey of the 10 repos, 14 plugin classes)

| Plugin | Declaration | Target mapping | Tool models to separate | Also |
|---|---|---|---|---|
| **LangBiTe** | `@system_under_test("openai")` | a new OpenAI-compatible model entry filled from `AISC_TARGET_*` (base URL, key, model) | the sentiment judge: its own model and key fields, today hard-coded GPT-4 on the target's key | the form's model list and key become the judge's |
| **StrongREJECT** | `@system_under_test("openai")` | `target_model` field, `AISC_TARGET_*` for its litellm call | judge and PAIR attacker: own fields, today gpt-4o-mini on the target's key | bug: PAIR always attacks gpt-4o-mini (`victim_model` never passed) |
| **Promptfoo** | `@system_under_test("openai")` | target provider set to the target's endpoint | the llm-rubric grader and the red-team generator: own provider fields, today the target's settings | none |
| **LLM-eval** (3 classes) | `@system_under_test("openai", needs=("logprobs",))`, or inputs when predictions are uploaded | its `endpoint` field | the judge: own `judge_endpoint`, today the target's `endpoint` | the platform's OpenAI facade gives no logprobs: the target must itself be OpenAI-compatible, or upload predictions |
| **AgentDojo** | `@system_under_test("openai", needs=("tools",))` | its `local` path, `AISC_TARGET_*` | none | the facade carries no tool calls: only an OpenAI-compatible agent endpoint works; MCAS is not an agent |
| **Ragas** | `@assesses_inputs()` | none (the dataset holds the answers) | judge and embeddings already explicit; remove the `OPENAI_API_KEY` fallback (R3) | none |
| **Data drift, data anomaly** | `@dataset_through_target(...)` optional, else `@assesses_inputs()` | the scorer's endpoint, via 4.3 | none | none |
| **Fairness, performance (2), ExpliTest** | `@assesses_inputs()` now; `@dataset_through_target` once they take a predictions column | via 4.3 later | none | change per plugin, P6 |

Each plugin is changed in its own repo (lux-ai-factory/aisc-plugin-*), test-first, its version
bumped, rebuilt into the stack's devpi by plugin-publisher, and checked by verify-plugins.sh.

## 6. The MCAS trials

MCAS runs on Scaleway (private, header X-Auth-Token, token in ~/mcas-demo-token.txt). It is now
1 vCPU and 1 worker until it is scaled up again on Tue 2026-10-06 (~/mcas-tuesday-scale-up.md).

- **Project and targets.** A project with an AI card for MCAS whose components include the chat
  assistant (LLM) and the scoring model (model). Each becomes a target.
- **Endpoints, in Manage, Targets and endpoints:**
  - chat assistant: REST `POST /chat`, body `{"question": "{{input}}", "history": "{{history}}"}`,
    answer at `answer`, refusal on HTTP 502 (MCAS refuses what its policy clauses don't cover);
  - scoring model: REST `POST /score`, body `{{input}}` (the applicant row as it is), answer the
    whole JSON (`score`, `recommendation`, `band`, ...).
- **Trial 1, LangBiTe on the chat assistant**, after P3: one concern (gender), a few templates,
  judge on its own key. A refusal counts as its own outcome, neither pass nor fail.
- **Trial 2, data drift on the scoring model**, after P4: a reference set and a shifted set of
  applicants, both sent through `/score`; drift on the score and the recommendation. One call at a
  time while MCAS has 1 vCPU (about 0.5 s each locally, longer there).
- Results on the dashboard, the report, and the ledger's Activity log for both runs.

## 7. Phases (each test-first; local commits; pushes only with a yes, repos named)

| Phase | What | Stops for |
|---|---|---|
| P1 | done: dropdown names, endpoint refusal | |
| P2 | done: survey (section 5) | the decisions in section 9 |
| P3 | the declarations and capability check in plugin-interface (4.2); LangBiTe to the standard; Trial 1 | the user's look at Trial 1 |
| P4 | `@dataset_through_target` (4.3); data drift to the standard; Trial 2 | the user's look at Trial 2 |
| P5 | the conformance check (4.4) and the README section; StrongREJECT (with its bug), Promptfoo | |
| P6 | LLM-eval, AgentDojo; `@assesses_inputs` on Ragas and the file plugins; fairness and performance on a predictions column | |
| P7 | push all repos (named, after a yes); a fresh clone from the README passes `verify.sh --stack` with the conformance check | the push yes |

Stopping rule for every phase: a plugin whose own tests fail before any change is reported, not
patched around; a capability the platform lacks (tools, logprobs) is recorded as a refusal (R4),
not emulated.

## 7b. Branches

Everything is done on `feat/unified-modules`, in every repo, plugin repos included:
- aisc and its submodules (plugin-interface among them) are on it already;
- of the 10 plugin repos only aisc-plugin-langbite has it (4 commits ahead of main: conversation
  histories before the test prompt, three MCAS histories, and an MCAS-specific chat backend). The
  other 9 get it, made from their main, with the first change;
- plugin-downloader clones `--branch feat/unified-modules` where a repo has it, else the default
  branch, so the stack builds what the standard changes (a test of the downloader, like the others);
- LangBiTe's MCAS-specific backend is replaced by the standard target path (P3); its histories stay
  and work with any target.

## 8. Not in this plan

Sean's webapp and engine (a real filter in the dropdown, plan option B, waits for him); the six
private plugin repos (left out of the workshop by the user's choice); streaming; plugins that run
their own models in-process (they keep doing so: that is their input, not a target).

## 9. Decisions for the user

1. The rules R1 to R5 as the standard.
2. The new declarations `@assesses_inputs` and `@dataset_through_target`, and `needs=` on
   `@system_under_test`, in the shared plugin contract (plugin-interface, used by every plugin).
3. The order P3 to P7 (LangBiTe and the MCAS chat first, then data drift and the MCAS scorer).
4. Changing all 10 plugin repos; each push named and asked for.
5. The MCAS card: an existing card with the chat assistant and the scoring model as components, or
   one to make for the trial.
6. The workshop date, to fit the phases before it.
7. Decided 2026-10-04: LangBiTe's branch feat/unified-modules stays; its MCAS-specific chat backend
   (llm_mcas_service.py, the MCASChat entry, MCAS_URL) is removed in P3; the conversation histories
   stay, and P3 adds a history choice (default none) to the plugin's form.
