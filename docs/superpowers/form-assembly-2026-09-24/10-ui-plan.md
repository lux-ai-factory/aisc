# 10. UI plan: make the form-assembly pages siblings of the qualify form

Date: 2026-09-25. Planner pass only, no code changed. App: `apps/qualification`, branch
`feat/unified-modules`, uncommitted tree. Baseline before any change: `npx vitest run` gives
77 files passed, 4 skipped; 912 tests passed, 38 skipped. The 7 files that pin these pages
(FormBuilder, FormsPage, FormImport, FormChooser, FormLine, widePage, SiteHeader) pass 64/64.

Scope: markup and CSS only. No change to behaviour, exported props, server actions, data,
routes or Python. Every accessible name, label and text a test relies on is kept (section 2).

## 0. Root causes (why it looks the way it does)

1. **Nothing new has CSS.** `grep` finds no rule for `qf-builder*`, `qf-chooser*`, `qf-import*`,
   `qf-overlap`, `qf-new-wording` or `qf-row-form`.
2. **The builder is outside `.qualify-form`.** Nearly every form rule in `globals.css` is scoped
   `.qualify-form .qf-*` (panel `.qf-section`, `.qf-help`, `.qf-citation` chip, `.qf-tag`,
   `.qf-group`, `textarea`, `.qf-actions`). `FormBuilder` renders `<div className="qf-builder">`
   with no `.qualify-form` ancestor, so the citation chip, tags, panels and action bar all fall
   back to browser defaults. That causes problems 7, 8, 13 and 14, and "Your form" is not a panel.
3. **`.qf-row` means two things.** Globally (line 1289) it is the Versions list row (`display:
   flex; justify-content: space-between; padding: 18px 4px; :hover` tint). Inside `.qualify-form`
   it is a two-column grid. The builder's "Start from" wrapper gets the list-row version (tiny
   select, huge Apply: problem 10). The import rows get the two-column grid with 6 children.
4. **`.onto-table` is the ontology key/value table.** Its `td { display: flex; flex-wrap: wrap }`
   and `th { width: 210px }` make every `td` of a row stack as its own block (problems 1, 3).
5. **`.btn` is `width: 100%` by default.** Only contexts that override it (`.qualify-form
   .qf-actions .btn`, `.qf-list-actions .btn`, `.qf-header-btn`) get normal buttons. The builder
   has none, so every button is full width (problem 14).
6. **Widths:** library is `qualify-page` (820px), builder, edit and import are
   `qualify-page--wide` (up to 1900px): problem 15.
7. **Site header (problem 5):** `src/app/p/[project]/layout.tsx` renders `<SiteHeader project>`
   for every route under `/p/[project]`, forms included, and `SiteHeader.test.tsx` pins its
   "← Back" link. The screenshot shows no header, so either the running image predates this or
   it was captured without it. Task 0 checks this in the running app; it is not a markup fix. The
   plan still adds a "← Forms" crumb to the three builder pages so the way back is on the page.
8. **Problem 13 (editor always open):** in code the editor only mounts after "+ New question"
   (`editor` state starts `null`). The screenshot was most likely taken after pressing it. The
   fix is visual: the editor becomes a clearly bounded inset panel with a heading, and its select
   gets a real style.

## 1. Design rules taken from the existing pages

Tokens only: `--primary`, `--accent`, `--panel`, `--panel-2`, `--border`, `--border-strong`,
`--muted`, `--info-soft`, `--pink-soft`, `--graph-muted`, `--radius` (0). Shapes and patterns
reused, not invented:

| Need | Existing pattern reused |
|---|---|
| Page header with primary buttons on the right | card page: `.qf-header-row` + `.qf-header-actions` + `.btn qf-header-btn` |
| White panel | `.qualify-form .qf-section` |
| Small uppercase group head | `.qualify-form .qf-group` |
| Citation chip | `.qualify-form .qf-citation` (pill, primary text, panel-2) |
| Status tag | `.qualify-form .qf-tag` (square, uppercase, 11px) |
| Chip toggle | `.qf-chip` / `.qf-chip.active` (pill, primary when on) |
| Notice box | `.qf-prefilled` (info-soft, 3px primary left rule) |
| Warning chip | `.onto-flag` palette (pink-soft, accent border, #8a0044 text) |
| Small data table | `.method-stops` (10px uppercase thead, 1px row rules) |
| Numbered square counter | `.method-loop > li::before` |
| Crumb | `.qf-crumb` |
| Checkbox colour | `.onto-popover .onto-checkbox input { accent-color: var(--primary) }` |

One page width for the whole forms area: `qualify-page--form` (1080px), the existing width for
"a form being filled in", which the widePage test already pins. It is wide enough for two
builder columns and not full bleed.

## 2. Tests that constrain the markup (must pass unchanged)

| Test file | What it pins | Consequence for the plan |
|---|---|---|
| `FormsPage.test.tsx` | `header p` (first one) contains the two R48 sentences; rows are `tbody tr`; `getByText(name).closest("tr")`; row links in order exactly "Start from", "Edit" (non-builtin), "Export CSV", "Export Markdown"; export hrefs and `download`; every `<a>` href starts `/p/<project>/`; no "Set as default" | keep a `<table>`; the name must be an element whose own text is exactly the name (a `<strong>` is fine); keep link texts; header buttons are fine because their hrefs start `/p/a/`; intro `p` stays the first `p` in the page header |
| `FormBuilder.test.tsx` | regions "Question library" and "Your form"; `heading` per group in the left; 5 checkboxes left, named by their question text; `span.qf-citation` in both columns; R29 `closest("li, label, div")` of a checkbox has no chip for a citation-less question; labels "Search questions", "Start from", "Form name", "Answers Annex IV point"; buttons "Apply", "+ New question", "Save question", "Save form", "Save as v<N>", "Use once", `/^Edit/`, `/^Remove/`, `Move <40 chars> up/down`, "Use the new wording of ..."; `right().textContent` contains "Always included: System name, Version, Company (provider)"; block checkboxes named exactly by label, none for the identity fields; `getAllByText("≈ overlaps Annex IV(2)(a)")` in both columns; 3 `[draggable='true']` rows; placeholder "e.g. Acme AI Policy §4.2"; `div.error` text; `span.qf-tag` exactly "Source updated"; `p.qf-new-wording` textContent exactly "New wording: <text>"; button text "Use new wording" | checkbox stays the direct child of its `<label>`; chips stay `span`s with their exact own text; identity text must still concatenate to the exact sentence (visually hidden separators, see 4.4); no extra `div` between a library checkbox and its `label` |
| `FormImport.test.tsx` | file `input[type=file]`; text "Found N questions in <file>"; all `li` textContents include each warning; `getByDisplayValue` on question and citation; checkboxes named "Required"; `/^Remove/` buttons; "Continue with M questions"; `getAllByLabelText("Answers Annex IV point")` returns the selects; after confirm, region "Your form", checkbox "Risks", "Save form" | keep `aria-label`s on the two inputs (a visible `<label>` must not be added to them, it would not change the name but is noise); keep the per-row `<label htmlFor>` for the select; list items for rows are allowed |
| `FormChooser.test.tsx` | `group` "Which form?" (fieldset + legend); radio names by form name; label textContent ends with `default` for the default; a `span.qf-tag` whose text is exactly `" default"` (leading space) only on the default; `.qf-chooser-name`; "same as v4"; "Same form as v2" option first; links "+ New form", "Import form"; button "Continue"; error text | keep the `" default"` text; tags may move into a wrapper `span` but must stay last in the label; do not reorder options |
| `FormLine.test.tsx` | `p.qf-row-form` textContent exactly `Form: <name> v<N> · CSV · Markdown`; link names via `aria-label`; hrefs; `download`; card and edit pages render `<FormLine` and no `Form: {` | separators may be wrapped in spans, no text may be added or removed |
| `widePage.test.ts` | card page is `qualify-page qualify-page--wide`; `.qualify-page--wide` max-width `min(1900px,`; `.qualify-page--form` `max-width: 1080px`; `.qualify-page` `max-width: 820px`; system/edit page is `--form` and not `--wide` | do not touch those three rules; forms pages may use `--form` |
| `SiteHeader.test.tsx` | nav texts and Forms href | SiteHeader not touched |
| `formActions.test.ts` | the forms files exist under `/p/[project]/`; edit page 404 for builtin | no file moves or renames |
| `VerticalCard.test.tsx` | uses `.onto-table` for the card | `.onto-table` rules are not edited; the library just stops using it |

## 3. Library page, `/p/[project]/forms`

### 3.1 Target

```
 [site header: logo | ← Back  AI system  Versions  Forms  Methodology]

 Forms                                             [ Import form ] [ + New form ]
 The questions an AI card asks. Every project on this install
 sees the same forms. A new AI card starts with the Annex IV
 default. Build a form from the library, or import one from a file.

 FORM                              VERSION  QUESTIONS  MADE BY
 ───────────────────────────────────────────────────────────────────────────────
 Annex IV default  [DEFAULT]       v1       14         Built in    [Start from]  Export CSV  Export Markdown
 EU AI Act Annex IV points 1 and 2, as 14 questions.
 ───────────────────────────────────────────────────────────────────────────────
 Acme AI policy                    v3       18         Imported    [Start from] [Edit]  Export CSV  Export Markdown
```

Width 1080px, same as the builder. Below 720px the table scrolls horizontally inside its
wrapper and the actions wrap.

### 3.2 Markup (`src/app/p/[project]/forms/page.tsx`)

- `<main className="qualify-page qualify-page--form qf-forms-page">`.
- Header: `<header className="qualify-header"><div className="qf-header-row"><div><h1>Forms</h1><p>`
  intro, with the two `Link`s **removed from the `<p>`** `</p></div><div className="qf-header-actions">`
  `<Link className="btn ghost qf-header-btn" href=".../forms/import">Import form</Link>`
  `<Link className="btn qf-header-btn" href=".../forms/new">+ New form</Link></div></div></header>`.
  The intro `p` keeps its sentences verbatim (R48) and ends at "...import one from a file."
- `<div className="qf-forms-scroll"><table className="qf-forms-table">` (replaces `onto-table`).
- `thead`: `<th>Form</th><th>Version</th><th>Questions</th><th>Made by</th><th><span className="qf-sr">Actions</span></th>`
  (the empty header gets a visually hidden name).
- Name cell `<td className="qf-forms-name">`: `<strong>{r.name}</strong>`,
  `{r.isDefault && <span className="qf-tag qf-tag--default">default</span>}`,
  `{r.description && <p className="qf-forms-desc">{r.description}</p>}` (`description` is already
  on `LibraryRow`).
- `<td className="qf-forms-num">v{r.version}</td>`, `<td className="qf-forms-num">{r.questionCount}</td>`
  (the word "questions" moves to the column head; ASSUMED: acceptable, no test reads it).
- Made by: a display map in the page, `const MADE_BY: Record<string, string> = { builtin: "Built in",
  builder: "Form builder", import: "Imported" }`, rendered `{MADE_BY[r.origin] ?? r.origin}`.
  Presentation of a stored value, not a data change. Taste default, named here.
- Actions `<td>` holds a wrapper, never flex on the `td` itself:
  `<div className="qf-forms-actions">` with `Link.btn.ghost` "Start from", `Link.btn.ghost` "Edit"
  (non-builtin), then `<a className="qf-forms-export" download>` "Export CSV" and "Export
  Markdown". The `" · "` text separators are deleted (gap does the spacing). Link order unchanged.

### 3.3 CSS (new section, see section 9 for the full list)

```
.qf-forms-scroll { overflow-x: auto; }
.qf-forms-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.qf-forms-table thead th { text-align: left; padding: 0 16px 8px 0; border-bottom: 2px solid var(--border-strong);
  font-size: 10px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); white-space: nowrap; }
.qf-forms-table td { padding: 16px 16px 16px 0; border-bottom: 1px solid var(--border); vertical-align: top; }
.qf-forms-table tbody tr:hover { background: var(--panel-2); }
.qf-forms-name strong { font-size: 16px; font-weight: 700; }
.qf-forms-desc { margin: 4px 0 0; font-size: 13px; color: var(--muted); }
.qf-forms-num { font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--graph-muted); }
.qf-forms-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px 14px; }
.qf-forms-actions .btn { width: auto; padding: 7px 12px; font-size: 13px; }
.qf-forms-export { font-size: 13px; font-weight: 600; white-space: nowrap; }
.qf-tag--default { background: var(--info-soft); border-color: var(--primary); color: var(--primary); margin-left: 8px; vertical-align: 2px; }
.qf-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
```

`.qf-tag` is scoped to `.qualify-form`; extend the selector list of that existing rule (and of
`.qualify-form .qf-citation`) with `.qf-forms-page .qf-tag` / `.qf-forms-page .qf-citation`
instead of copying the declarations. The widePage guards do not read those rules.

`@media (max-width: 720px) { .qf-forms-page .qf-header-row { flex-direction: column; } }`
(scoped, so the card page is unchanged).

## 4. Builder (`/forms/new`, `/forms/[formId]/edit`, import after confirm)

### 4.1 Target

```
 ← Forms
 New form
 Tick questions from the library, write your own, and choose the blocks the form asks for.

 ┌ Question library ─────────────────────────┐  ┌ Your form (sticky) ───────────────┐
 │ SEARCH QUESTIONS                          │  │ FORM NAME                         │
 │ [.....................................]   │  │ [...............................] │
 │ START FROM                                │  │ BLOCKS                            │
 │ [Choose a form...            v] [Apply]   │  │ Always included: (✓ System name)  │
 │                                           │  │  (✓ Version) (✓ Company)          │
 │ ANNEX IV DEFAULT ──────────────────────── │  │ (☑ Short description) (☑ Target   │
 │ ☐ If this version replaces an earlier     │  │  use case) (☐ Risks) ...          │
 │   one, describe what changed and why...   │  │ QUESTIONS (3) ─────────────────── │
 │   (ANNEX IV(1)(A))                        │  │ [1] Who signs off a model release?│
 │ ☑ How was the system built, step by      │  │     (§4.2) from Acme  [REQUIRED]  │
 │   step? Include any pre-trained models... │  │     [↑][↓]           Edit  Remove │
 │   (ANNEX IV(2)(A)) (≈ overlaps IV(2)(a)) │  │ [2] ...                            │
 │ ...                                       │  │ [ + New question ] (dashed)        │
 │ ACME AI POLICY ────────────────────────── │  │ ───────────────────────────────── │
 │ ☐ Who signs off a model release?          │  │          [ Use once ] [ Save form ]│
 └───────────────────────────────────────────┘  └───────────────────────────────────┘
```

Columns: `minmax(0, 1fr) minmax(360px, 420px)`, gap 24px, inside the 1080px page. The right
column is `position: sticky` under the 89px site header (`top: 105px`), scrolls on its own
(`max-height: calc(100vh - 121px); overflow-y: auto`) and its footer sticks to its bottom.
Below 960px: one column, library first (spec section 7), the library's question list capped at
`max-height: 60vh` with its own scroll so "Your form" is reachable, the right column static.

When the editor is open it replaces the "+ New question" button, inside the right column:

```
 │ NEW QUESTION  (or: EDIT QUESTION 2)       │
 │ ┃ QUESTION                                │
 │ ┃ [textarea, 3 rows.....................] │
 │ ┃ CITATION             ANSWERS ANNEX IV   │
 │ ┃ [e.g. Acme AI...]    [None          v]  │
 │ ┃ ☑ Required                              │
 │ ┃                  Cancel [Save question] │
```

Inset panel (panel-2 background, 3px primary left rule, like `.qf-prefilled`), small buttons.
The form footer buttons are large and at the bottom: editor actions and form actions can no
longer be confused.

### 4.2 Page shells

- `forms/new/page.tsx`, `forms/[formId]/edit/page.tsx`, `forms/import/page.tsx`:
  `<main className="qualify-page qualify-page--form qf-forms-page">` (was `--wide`), and first
  in the header `<p className="qf-crumb"><Link href={`/p/${project}/forms`}>← Forms</Link></p>`.
  `qf-crumb` already has CSS. ASSUMED: the crumb is not the first `p` of a header in the library
  page (it is not added there), so FormsPage R48 is unaffected.

### 4.3 Markup (`src/app/p/[project]/forms/FormBuilder.tsx`)

Root: `<div className="qualify-form qf-builder">`. Adding `qualify-form` switches on the panel,
chip, tag, group head, textarea and action-bar rules. Checked side effects: `.qualify-form .qf-row`
(avoided, see below), `.qualify-form .field:first-of-type .qf-group` (no `.qf-group` sits inside a
`.field` here), placeholders (wanted).

Left, `<section aria-label="Question library" className="qf-section qf-builder-library">`:
- `<div className="qf-builder-toolbar">` holds the search `.field` and
  `<div className="qf-builder-startfrom">` (replaces `className="qf-row"`, which is what broke
  problem 10). Inside: the "Start from" `.field` with `<select className="qf-select">`, then the
  Apply button `className="btn ghost qf-builder-apply"`.
- Groups wrapped in `<div className="qf-builder-groups">` (the element capped at 60vh on narrow).
- Each group: `h3.qf-group` (unchanged), `ul.qf-builder-list`, `li`, `label.qf-builder-pick`
  with, in order: the checkbox (still the label's direct child), then
  `<span className="qf-builder-pick-body">` containing `<span className="qf-question-text">`
  and, when any chip exists, `<span className="qf-builder-chips">` with `span.qf-citation` and
  `span.qf-overlap`. The `{" "}` text node after the checkbox is removed (the grid gap spaces
  it). The text and the chip are now separate boxes on separate lines, so "...that.Annex IV(1)(a)"
  cannot happen (problem 8).

Right, `<section aria-label="Your form" className="qf-section qf-builder-form">`, in this order:
1. Name: `.field` with "Form name" input (new) or `<h2>{state.name}</h2>` (edit), unchanged.
2. `<h3 className="qf-group">Blocks</h3>`.
3. Identity, replacing `<p className="qf-help">{ALWAYS_INCLUDED}</p>`:
   ```
   <p className="qf-builder-identity">
     <span className="qf-builder-identity-label">Always included: </span>
     {IDENTITY_FIELDS.map((id, i) => <Fragment key={id}>
        {i > 0 && <span className="qf-sr">, </span>}
        <span className="qf-builder-locked">{METADATA_FIELDS[id].label}</span></Fragment>)}
   </p>
   ```
   textContent stays exactly "Always included: System name, Version, Company (provider)" (R21
   test). The `ALWAYS_INCLUDED` constant goes (or stays for a `title`; either is fine).
4. `div.qf-builder-blocks` of `label.qf-builder-block` (unchanged markup, now styled as chips;
   remove the `{" "}` after each input).
5. `<h3 className="qf-group">Questions ({state.questions.length})</h3>`; when the list is empty,
   `<p className="qf-builder-empty">No questions yet. Tick them in the library, or start from a form.</p>`.
6. `ol.qf-builder-rows` > `li.qf-builder-row` (still `draggable`, same handlers), restructured:
   ```
   <span className="qf-builder-pos">{i + 1}</span>          (was "1." plus a space)
   <div className="qf-builder-row-body">
     <span className="qf-question-text">{w.text}</span>
     <div className="qf-builder-chips">
       citation span.qf-citation, span.qf-builder-owner, span.qf-overlap, span.qf-tag Required/Optional
     </div>
     {update && <div className="qf-builder-update">
        <span className="qf-tag qf-tag--notice">Source updated</span>
        <p className="qf-new-wording">New wording: {update.question.text}</p>   (text unchanged)
        <button className="btn ghost qf-builder-tool" ...>Use new wording</button>
     </div>}
     <div className="qf-builder-actions">
        <span className="qf-builder-move">↑ ↓ buttons, className="qf-builder-tool qf-builder-arrow"</span>
        Edit, Remove buttons, className="qf-builder-tool" / "qf-builder-tool qf-builder-remove"
     </div>
   </div>
   ```
   All aria-labels, texts, `disabled` and `ref` logic unchanged. `.btn ghost` is dropped from
   the row tools (they are text tools, not buttons of the page's weight); "Use new wording"
   keeps `btn ghost` plus the small modifier.
7. Editor or add button: when `editor` is set, `<div className="qf-builder-editor">` with a
   heading `<h3 className="qf-group">{editor.index === null ? "New question" : `Edit question ${editor.index + 1}`}</h3>`
   then `QuestionEditor` (internal component, props unchanged). Otherwise
   `<button className="btn ghost qf-builder-add">+ New question</button>`.
8. `{error && <div className="error">}` (unchanged), then
   `<div className="qf-actions qf-builder-footer">` with **"Use once" first, then "Save form" /
   "Save as vN"**, so the primary sits rightmost as on every other page. Classes unchanged:
   primary `btn`, secondary `btn ghost`.

`QuestionEditor` (same file, internal): root loses its own class (the wrapper in 7 carries
`qf-builder-editor`); the citation `.field` and the Annex point `.field` go into
`<div className="qf-builder-editor-pair">`; the select gets `className="qf-select"`; the
Required label becomes `className="qf-builder-check"`; actions become
`<div className="qf-actions qf-builder-editor-actions">` with **Cancel first** (`btn ghost
qf-builder-small`), then Save question (`btn qf-builder-small`).

### 4.4 CSS

```
/* frame */
.qf-builder { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 420px); gap: 24px; align-items: start; }
.qf-builder > .qf-section { margin-bottom: 0; }
.qf-builder-form { position: sticky; top: 105px; max-height: calc(100vh - 121px); overflow-y: auto; padding-bottom: 0; }
@media (max-width: 960px) {
  .qf-builder { grid-template-columns: 1fr; }
  .qf-builder-form { position: static; max-height: none; overflow: visible; }
  .qf-builder-groups { max-height: 60vh; overflow-y: auto; }
}
.qf-builder input[type="checkbox"], .qf-import-row input[type="checkbox"], .qf-chooser input[type="radio"]
  { accent-color: var(--primary); width: 16px; height: 16px; margin: 0; flex: none; }

/* shared select, same look as .field input */
.qualify-form select.qf-select { width: 100%; background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
  padding: 10px 12px; font: inherit; font-size: 14px; color: var(--text); cursor: pointer; }
.qualify-form select.qf-select:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(0,15,223,.1); }

/* library toolbar */
.qf-builder-startfrom { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: end; }
.qf-builder-startfrom .field { margin-bottom: 0; }
.qf-builder-apply { width: auto; padding: 10px 16px; }

/* library rows */
.qf-builder-list { list-style: none; margin: 0; padding: 0; }
.qf-builder-list > li + li { border-top: 1px solid var(--border); }
.qf-builder-pick { display: grid; grid-template-columns: 16px 1fr; gap: 12px; padding: 12px 10px; cursor: pointer;
  font-size: 14px; line-height: 1.55; border-left: 3px solid transparent; }
.qf-builder-pick input { margin-top: 3px; }
.qf-builder-pick:hover { background: var(--panel-2); }
.qf-builder-pick:has(input:checked) { background: var(--info-soft); border-left-color: var(--primary); }
.qf-builder-pick .qf-question-text { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.qf-builder-pick:hover .qf-question-text, .qf-builder-pick:focus-within .qf-question-text,
.qf-builder-pick:has(input:checked) .qf-question-text { -webkit-line-clamp: unset; display: block; }
.qf-builder-chips { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 6px; }
.qf-overlap { font-size: 11px; font-weight: 700; color: #8a0044; background: var(--pink-soft);
  border: 1px solid var(--accent); border-radius: 999px; padding: 2px 9px; white-space: nowrap; }

/* blocks */
.qf-builder-identity { margin: 0 0 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); }
.qf-builder-locked { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px;
  background: var(--panel-2); border: 1px dashed var(--border-strong); color: var(--graph-muted); font-size: 12px; font-weight: 600; cursor: default; }
.qf-builder-locked::before { content: "✓"; font-weight: 800; color: var(--muted); }
.qf-builder-blocks { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
.qf-builder-block { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px;
  border: 1px solid var(--border); background: #fff; font-size: 12px; font-weight: 600; cursor: pointer; }
.qf-builder-block:hover { border-color: var(--primary); color: var(--primary); }
.qf-builder-block:has(input:checked) { border-color: var(--primary); background: var(--info-soft); color: var(--primary); }

/* picked rows */
.qf-builder-empty { color: var(--muted); font-size: 13px; font-style: italic; margin: 0 0 12px; }
.qf-builder-rows { list-style: none; margin: 0 0 12px; padding: 0; }
.qf-builder-row { display: grid; grid-template-columns: 26px 1fr; gap: 12px; padding: 12px 0; border-top: 1px solid var(--border);
  font-size: 14px; line-height: 1.5; cursor: grab; }
.qf-builder-row:first-child { border-top: 0; }
.qf-builder-row:hover { background: var(--panel-2); }
.qf-builder-pos { width: 26px; height: 26px; line-height: 25px; text-align: center; border: 1px solid var(--primary);
  color: var(--primary); font-size: 12px; font-weight: 800; font-variant-numeric: tabular-nums; }
.qf-builder-row .qf-question-text { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.qf-builder-row:hover .qf-question-text, .qf-builder-row:focus-within .qf-question-text { -webkit-line-clamp: unset; display: block; }
.qf-builder-owner { font-size: 12px; color: var(--muted); }
.qf-builder-owner::before { content: "from "; }
.qf-builder-actions { display: flex; align-items: center; gap: 4px 12px; margin-top: 8px; }
.qf-builder-move { display: inline-flex; gap: 4px; margin-right: auto; }
.qf-builder-tool { background: none; border: 0; padding: 2px 0; font: inherit; font-size: 12px; font-weight: 700; color: var(--muted); cursor: pointer; }
.qf-builder-tool:hover:not(:disabled) { color: var(--primary); }
.qf-builder-tool:disabled { opacity: .35; cursor: default; }
.qf-builder-arrow { width: 26px; height: 26px; padding: 0; border: 1px solid var(--border); background: #fff; }
.qf-builder-remove:hover:not(:disabled) { color: var(--error); }
.qf-builder-update { margin-top: 8px; padding: 8px 12px; background: var(--info-soft); border-left: 3px solid var(--primary); font-size: 13px; }
.qf-builder-update .qf-new-wording { margin: 4px 0 8px; }
.qf-builder-update .btn { width: auto; padding: 6px 12px; font-size: 12px; }
.qf-tag--notice { background: var(--pink-soft); border-color: var(--accent); color: #8a0044; }

/* add, editor, footer */
.qf-builder-add { border-style: dashed; margin-bottom: 16px; }          (full width is right here)
.qf-builder-editor { margin: 0 0 16px; padding: 4px 16px 12px; background: var(--panel-2); border-left: 3px solid var(--primary); }
.qf-builder-editor .qf-group { border-top: 0; padding-top: 0; margin-top: 12px; }
.qf-builder-editor-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.qf-builder-check { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; margin-bottom: 10px; }
.qualify-form .qf-builder-editor-actions { gap: 8px; margin-top: 0; }
.qualify-form .qf-builder-editor-actions .btn { padding: 8px 14px; font-size: 13px; }
.qualify-form .qf-builder-footer { position: sticky; bottom: 0; gap: 8px; margin: 0 -24px; padding: 14px 24px;
  background: var(--panel); border-top: 1px solid var(--border); }
```

(The right section keeps its 24px side padding; the footer's negative margins make its rule
run edge to edge. `padding-bottom: 0` on the section lets the footer sit flush at the bottom.)

### 4.5 "Source updated" and "≈ overlaps"

- "≈ overlaps Annex IV(x)" is a warning, not a citation: pink pill (onto-flag palette), shown in
  the same chip line as the citation in both columns, never glued to text.
- "Source updated": an info-soft notice box inside the row, under the current wording, holding a
  pink `qf-tag--notice` "Source updated", the new wording as its own paragraph, and a small
  "Use new wording" ghost button. Old wording stays visible above for comparison. All texts
  and aria-labels unchanged.

## 5. Import page, `/p/[project]/forms/import`

### 5.1 Target

```
 ← Forms
 Import a form
 One question per row or line. Headings are skipped, ...

 ┌──────────────────────────────────────────────────────────────┐
 │ FORM FILE (CSV, MARKDOWN OR WORD)                            │
 │ ┌ - - - - - - - - - - - - - - - - - - - - - - - - - - - - ┐  │
 │   [Choose file]  no file selected                            │
 │ └ - - - - - - - - - - - - - - - - - - - - - - - - - - - - ┘  │
 │ Reading the file...                                          │
 └──────────────────────────────────────────────────────────────┘
 ┌──────────────────────────────────────────────────────────────┐
 │ Found 3 questions in acme.csv                                │
 │ ┃ Skipped 1 heading.  Removed 1 duplicate question.          │
 │ [1] [Who signs off a model release?..................] Remove│
 │     [Acme AI Policy §4.2]  ANNEX IV POINT [None  v] ☑ Required│
 │ [2] ...                                                      │
 │                                  [ Continue with 3 questions ]│
 └──────────────────────────────────────────────────────────────┘
```

### 5.2 Markup (`src/app/p/[project]/forms/import/FormImport.tsx`)

- Upload section: wrap the file input in `<div className="qf-import-drop">` (inside the same
  `.field`, after the label).
- Preview section: `<h2 className="qf-import-found">{`Found ${...} questions in ${...}`}</h2>`
  (was `<p>`; same own text, `findByText` still matches). Warnings: `ul.qf-help` becomes
  `ul.qf-import-warnings`.
- Rows: `<ol className="qf-import-rows">` of `<li className="qf-import-row">` (was
  `div.qf-row.qf-import-row`; dropping `qf-row` removes the two-column grid). Inside:
  `<span className="qf-builder-pos">{i + 1}</span>`, the question input
  (`className="qf-import-text"`), the Remove button (`className="qf-builder-tool qf-builder-remove"`),
  then `<div className="qf-import-meta">` with the citation input (`className="qf-import-cite"`,
  add `placeholder="Citation"`), `<div className="qf-import-point">` holding the existing
  `label.qf-field-label` + `select.qf-select`, and the Required label (`className="qf-builder-check"`).
  All `aria-label`s, `id`/`htmlFor`, texts unchanged. Warnings test still finds its `li`s
  (`toContain`), row `li`s are extra and harmless.
- Continue: unchanged (`.qf-actions` + `btn`).

### 5.3 CSS

```
.qf-import-drop { border: 1px dashed var(--border-strong); background: var(--panel-2); padding: 18px; }
.qf-import-drop input[type="file"] { font: inherit; font-size: 14px; }
.qf-import-drop input[type="file"]::file-selector-button { font: inherit; font-size: 13px; font-weight: 800; color: var(--primary);
  background: #fff; border: 1px solid var(--primary); padding: 8px 14px; margin-right: 12px; cursor: pointer; }
.qf-import-found { font-size: 18px; margin: 0 0 10px; }
.qf-import-warnings { margin: 0 0 16px; padding: 8px 12px 8px 30px; background: var(--info-soft); border-left: 3px solid var(--primary); font-size: 13px; }
.qf-import-rows { list-style: none; margin: 0 0 8px; padding: 0; }
.qf-import-row { display: grid; grid-template-columns: 26px 1fr auto; gap: 8px 12px; align-items: center;
  padding: 12px 0; border-top: 1px solid var(--border); }
.qf-import-meta { grid-column: 2 / -1; display: grid; grid-template-columns: 1fr 220px auto; gap: 12px; align-items: end; }
.qf-import-row input:not([type]), .qf-import-row input[type="text"] { width: 100%; border: 1px solid var(--border); padding: 9px 12px;
  font: inherit; font-size: 14px; background: #fff; }
.qf-import-row input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(0,15,223,.1); outline: none; }
.qf-import-point .qf-field-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 4px; }
@media (max-width: 720px) { .qf-import-meta { grid-template-columns: 1fr; } }
```

## 6. "Which form?" chooser (`src/app/p/[project]/system/edit/FormChooser.tsx`)

Rendered by `system/edit/page.tsx` when no form is named (width `--form`, pinned by widePage).

### 6.1 Target

```
 Describe the AI system
 Choose the form to fill: its questions are what the AI card asks.

 ┌──────────────────────────────────────────────────────────────┐
 │ Which form?                                                  │
 │ ┌──────────────────────────────────────────────────────────┐ │
 │ │ ◉ Acme AI policy     v3 · 18 questions                    │ │  (checked: info-soft, primary border)
 │ └──────────────────────────────────────────────────────────┘ │
 │ ┌──────────────────────────────────────────────────────────┐ │
 │ │ ○ Annex IV default   v1 · 14 questions  [DEFAULT][SAME AS v4]│
 │ └──────────────────────────────────────────────────────────┘ │
 └──────────────────────────────────────────────────────────────┘
 [ + New form ] [ Import form ]                        [ Continue ]
```

### 6.2 Markup

- Wrap the tags of each option in `<span className="qf-chooser-tags">` (the `" default"` tag and
  the `" same as vN"` tag, both unchanged, in the same order, still last in the label: R43 test
  `/default\s*$/` and `span.qf-tag === " default"` keep passing). Add `qf-tag--default` to the
  default tag.
- The two meta spans: keep both; the second gets the separator by CSS
  (`.qf-chooser-meta + .qf-chooser-meta::before { content: "· " }`), no text change.
- Nothing else. The actions markup stays; CSS places "Continue" right.

### 6.3 CSS

```
.qf-chooser fieldset { margin: 0 0 20px; min-width: 0; }
.qf-chooser legend { float: left; width: 100%; padding: 0; margin: 0 0 14px; font-size: 18px; font-weight: 900; }
.qf-chooser-option { clear: both; display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; padding: 14px 16px;
  border: 1px solid var(--border); margin-bottom: 8px; cursor: pointer; }
.qf-chooser-option:hover { border-color: var(--primary); }
.qf-chooser-option:has(input:checked) { border-color: var(--primary); background: var(--info-soft); box-shadow: inset 3px 0 0 var(--primary); }
.qf-chooser-name { font-weight: 700; }
.qf-chooser-meta { font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }
.qf-chooser-meta + .qf-chooser-meta::before { content: "· "; }
.qf-chooser-tags { margin-left: auto; display: inline-flex; gap: 4px; }
.qualify-form.qf-chooser .qf-actions { justify-content: flex-start; gap: 8px; }
.qualify-form.qf-chooser .qf-actions .btn:last-child { margin-left: auto; }
```

## 7. The "Form: <name> vN · CSV · Markdown" line (`src/app/p/[project]/FormLine.tsx`)

Used in the card page header and the edit page header, inside `.qualify-header`, which gives
every `p` `margin-bottom: 32px` and muted colour: the line floats 32px under the intro and 32px
above the next thing.

### 7.1 Target

```
 Describe the AI system
 Saving makes v5 of the AI card; earlier versions stay as they were.
 FORM  Acme AI policy v3   [↓ CSV] [↓ MARKDOWN]
```

### 7.2 Markup

`<p className="qf-row-form"><span className="qf-row-form-name">Form: {formName} v{versionNumber}</span>`
`<span className="qf-row-form-sep"> · </span><a ...>CSV</a><span className="qf-row-form-sep"> · </span><a ...>Markdown</a></p>`.
textContent stays exactly `Form: Acme AI policy v3 · CSV · Markdown`; aria-labels, hrefs,
`download` unchanged.

### 7.3 CSS

```
.qualify-header p:has(+ .qf-row-form) { margin-bottom: 10px; }
.qualify-header .qf-row-form { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0 0 24px;
  font-size: 13px; font-weight: 600; color: var(--graph-muted); }
.qf-row-form-sep { display: none; }
.qf-row-form a { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
  border: 1px solid var(--border); background: var(--panel-2); padding: 2px 8px; }
.qf-row-form a::before { content: "↓ "; }
.qf-row-form a:hover { border-color: var(--primary); }
```

`display: none` hides the dots visually; the text stays in the DOM (jsdom `textContent` is
unaffected, screen readers skip it, the link names come from `aria-label`).

## 8. New tests: `test/unit/formsLayout.test.tsx` (jsdom) plus a CSS guard

One new file, same mocking as the existing page tests (copy the `vi.mock` block of
`FormsPage.test.tsx` and `FormBuilder.test.tsx`; fixtures from `test/support/forms`). Each `it`
is written first and seen failing before its markup lands.

Library (`L`):
- L1 each data row has exactly 5 `td` children of one `tr`, the table has class `qf-forms-table`,
  not `onto-table`, and the CSS rule `.qf-forms-table td` does not contain `display: flex`.
- L2 the default row's name cell holds `span.qf-tag.qf-tag--default` with text "default"; no
  other row has one.
- L3 the last cell holds `div.qf-forms-actions` containing all the row's links, and that cell's
  textContent contains no "·".
- L4 "+ New form" has class `btn` without `ghost`, "Import form" has `btn ghost`, both inside
  `.qf-header-actions`, and neither is inside the intro `header p`.
- L5 "Made by" shows "Built in" and "Imported" for the two fixture rows; no cell's text is
  "builtin" or "import".

Builder (`B`):
- B1 the root has classes `qualify-form` and `qf-builder`; its two element children are, in
  order, the regions "Question library" and "Your form" (two landmarks side by side).
- B2 CSS guard: rule `.qf-builder` has `grid-template-columns`; `.qf-builder-form` has
  `position: sticky`; a `@media (max-width: 960px)` block sets `.qf-builder` to one column.
- B3 each library checkbox is the first child of a `label.qf-builder-pick`; its
  `span.qf-question-text` and `span.qf-citation` are different elements, and the text span's
  textContent does not contain the citation.
- B4 no element in the builder has class `qf-row`; the "Start from" select and "Apply" button
  share one `.qf-builder-startfrom` parent; the select has class `qf-select`.
- B5 `.qf-builder-identity` has 3 `.qf-builder-locked` chips with no input inside, and every
  block checkbox is inside a `label.qf-builder-block` inside `.qf-builder-blocks`.
- B6 before "+ New question" no `.qf-builder-editor` exists; after it, `.qf-builder-editor`
  contains "Save question" (`btn`, no `ghost`) and "Cancel" (`btn ghost`), and neither is inside
  `.qf-builder-footer`; `.qf-builder-footer` contains "Save form" (`btn`, no `ghost`) and "Use
  once" (`btn ghost`), primary last.
- B7 in the "Your form" region, the picked row's move, Edit and Remove buttons are inside
  `.qf-builder-actions` and carry `qf-builder-tool`, not `btn`.
- B8 with the R64 fixture, the "Source updated" tag, `p.qf-new-wording` and "Use new wording"
  share one `.qf-builder-update` parent.

Import (`I`):
- I1 after a preview, each row is `li.qf-import-row` inside `ol.qf-import-rows`, and no element
  has class `qf-row`.

Chooser (`C`):
- C1 each option `label.qf-chooser-option` has its tags inside `.qf-chooser-tags`, the default
  tag also has `qf-tag--default`.

FormLine (`F`):
- F1 the two dots are `span.qf-row-form-sep` elements (textContent unchanged is already pinned
  by `FormLine.test.tsx`).

Pages (`P`, source reads like widePage):
- P1 `forms/page.tsx`, `forms/new/page.tsx`, `forms/[formId]/edit/page.tsx`,
  `forms/import/page.tsx` each contain `className="qualify-page qualify-page--form qf-forms-page"`
  and none contains `qualify-page--wide`.
- P2 the new, edit and import pages contain a `qf-crumb` link to `` `/p/${project}/forms` ``.

## 9. CSS placement

One new block at the end of `globals.css`, headed
`/* ── Form assembly: library, builder, import, chooser, form line ───────── */`, containing every
rule in 3.3, 4.4, 5.3, 6.3 and 7.3, in that order. The only edits outside the block are two
selector-list extensions (`.qualify-form .qf-tag` and `.qualify-form .qf-citation` gain
`.qf-forms-page .qf-tag` / `.qf-forms-page .qf-citation`). No existing declaration changes; the
three width rules that widePage pins are untouched.

## 10. Ordered tasks

Each task: write its tests from section 8, run them and see them fail, make the change, run them
green, then the whole suite. Proof command for "whole suite" everywhere below:
`cd apps/qualification && npx vitest run && npx tsc --noEmit` (expect 77+1 files passed, 4
skipped; 912 + new tests passed, 38 skipped; tsc clean).

| # | Task | Tests first | Proof command |
|---|---|---|---|
| 0 | Look at `/p/<project>/forms` in the running app and check the site header renders. If it does not, report it (stale image or embed), do not patch markup. No rebuild or redeploy of the shared stack without the owner's yes. | none | browser check, screenshot |
| 1 | Create `test/unit/formsLayout.test.tsx` with the shared mocks and the CSS `rule()` helper (copied from widePage). | none yet | `npx vitest run test/unit/formsLayout.test.tsx` runs (0 tests is fine) |
| 2 | Page shells: `--form` + `qf-forms-page` on the four pages, crumbs on three. | P1, P2 | `npx vitest run test/unit/formsLayout.test.tsx -t "P"` then whole suite (widePage, formActions stay green) |
| 3 | Library page markup + section 3.3 CSS + the two selector-list extensions. | L1 to L5 | `npx vitest run test/unit/formsLayout.test.tsx -t "L" test/unit/FormsPage.test.tsx` then whole suite |
| 4 | Builder frame: `qualify-form` on root, grid, sticky right column, responsive, `qf-select`, Start from toolbar. | B1, B2, B4 | `npx vitest run test/unit/formsLayout.test.tsx -t "B" test/unit/FormBuilder.test.tsx` |
| 5 | Library rows: pick label grid, body span, chip line, clamp, overlap chip. | B3 | same as 4 |
| 6 | Blocks and identity chips, "Blocks" / "Questions (N)" heads, empty hint. | B5 | same as 4, and check R21 still green |
| 7 | Picked rows: position square, body, chips, tools, "Source updated" box. | B7, B8 | same as 4 (R18 focus test and R64 tests stay green) |
| 8 | Editor panel and footer, button order and sizes. | B6 | same as 4, then `npx vitest run test/unit/FormImport.test.tsx` (the import mounts the builder) |
| 9 | Import page markup + 5.3 CSS. | I1 | `npx vitest run test/unit/formsLayout.test.tsx -t "I" test/unit/FormImport.test.tsx` |
| 10 | Chooser tag wrapper + 6.3 CSS. | C1 | `npx vitest run test/unit/formsLayout.test.tsx -t "C" test/unit/FormChooser.test.tsx` |
| 11 | FormLine separators + 7.3 CSS. | F1 | `npx vitest run test/unit/formsLayout.test.tsx -t "F" test/unit/FormLine.test.tsx test/unit/VerticalCard.test.tsx` |
| 12 | Whole suite, typecheck, lint; then a visual pass at 1440px and 800px wide on the library, new form (empty and with 3 picks and the editor open), edit, import preview, chooser and card header, compared against the 15 problems. | all | whole suite + `npx next lint`; screenshots |

Stopping rule: stop and report if any existing test needs editing to pass (that means a label or
text changed and the plan is wrong), or if a task needs a behaviour change.

## 11. Decisions taken by default (the owner may overrule in flight)

- One width, 1080px, for all forms pages (library included, was 820px).
- "Made by" labels: Built in, Form builder, Imported.
- Library question text clamped to 3 lines, fully shown on hover, focus or when ticked; picked
  rows clamp to 3 lines, full on hover or focus. No "show more" button (it would sit inside the
  checkbox's label).
- "Start from" stays in the library column, as spec section 7 says.
- Narrow screens: library first (spec), its list capped at 60vh so "Your form" is reachable.
- Question count column shows the number only, "Questions" is the column head.
- Footer and editor put the primary button rightmost (Use once, Save form; Cancel, Save question).
