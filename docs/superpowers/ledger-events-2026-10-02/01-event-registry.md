# Every event to log in immudb, across the six steps (2026-10-02)

User request: log everything (opened, closed, version, by whom, AI vs manual, ...) for each of the
six steps. Inventory of the code at feat/unified-modules 1cfd87a (aisc), CO 0084162/e0cfc1d, RG
4b2163a, read by three parallel searches. Supersedes the event table (section 6) of
~/aisc-fresh-2026-09-29b/aisc/docs/superpowers/ledger-2026-09-30/01-plan.md.

## Fields every event carries
`event_id`, `occurred_at`, `project_pid`, `card_version` (pid + number, when it applies), `step`
(0 platform/manage, 1-6), `action`, `actor_sub` + `actor_name` + `actor_kind` (user / ai / worker /
system / service), `on_behalf_of` (the user behind an AI or worker action), `item_type` + `item_id`
+ `item_version`, `before_sha256` / `after_sha256` (canonical JSON of the item), `content_ref`
(frozen copy), `outcome` (ok / failed / refused), `details` (small JSON, no secrets).

How each event is observed: **S** server code point exists; **B** browser only (needs a beacon:
page left, dialogs, unsaved edits).

## 0. Session, platform and Manage
| Event | Who | Obs | Key details |
|---|---|---|---|
| session.signed_in / signed_out | user | Keycloak event / B | realm, client |
| page.opened (every page of every app) | user | S (GET) | app, route, item ids, read_only (older version) |
| page.left (with unsaved_changes) | user | B | time on page |
| access.refused | any | S | path, 401/403/404, role needed |
| project.created / create_rolled_back / deleted / delete_refused | user/admin | S | name, owner, provisioning; deletion snapshot (members, versions) |
| member.added / role_changed / removed | owner | S | role before/after |
| card_version.created | user (via step 1) | S | number, name, version, provider |
| targets.synced, target.mirror_created / renamed | user/system | S | labels before/after |
| llm.provider.saved / removed / models_listed | admin | S | key fingerprint (never the key), base_url before/after |
| llm.choice.saved / removed | admin | S | system (card_agent, risk_mapper), provider/model before/after |
| llm.key.released | AI service | S | system, provider, model, refused |
| connection.saved (created/updated/revived) / deleted / tested | admin | S | full diff, secret set/kept/removed, test result |
| allowlist.host.allowed / removed | owner | S | host, note before/after |
| connection.secret.released, run_key.issued / used | system | S | connection, run, key fingerprint, use count |
| schema.viewed, pgadmin.opened | user | S | database |
| ui.step.opened (1-6 card clicked), ui.manage.opened, ui.project_delete.opened/cancelled | user | B | step, target URL |

## 1. Qualify (qualification app)
| Event | Who | Obs | Key details |
|---|---|---|---|
| question_set.created / version_created / save_unchanged / retired | user | S | questions added/removed/reworded, version n |
| questionnaire.created / version_created / used_once / retired / retire_refused | user | S | items, blocks, version n |
| question_set.exported / questionnaire.exported | user | S | format, file sha256 |
| question_set.file_read / questionnaire.file_read (import preview) | user | S | file sha256, counts |
| questionnaire.imported (self-contained / by reference) | user | S | ids created, file hash match |
| qualification.opened (card editor, card, versions list) | user | S | qualification id, version, read_only |
| document.prefill_read | user | S | file sha256, filled/kept/proposed (rule-based, no model) |
| qualification.created (= card submitted) / create_failed | user | S | answers sha256, risks, components carried vs new, questionnaire version |
| card.edit_refused_not_latest | user/AI | S | version |
| card.node_corrected / correction_reverted / corrections_discarded (manual) | user | S | node before/after, graph digest before/after |
| card.component_linked / relinked / unlinked (manual) | user | S | component, property, snapshot before |
| card.ai_refinement_requested | user | S | correlation id for the AI run |
| agent.run_queued / started / finished / failed | AI | S | on_behalf_of, model, rounds, calls, error |
| agent.model_resolved | AI | S | provider/model, project vs fallback |
| agent.llm_call | AI | S | purpose, property, round, model, prompt sha256, response sha256, latency |
| agent.property_drafted / reviewed / revised, agent.long_answers_named, agent.consistency_checked | AI | S | property, findings, notes |
| card.augmented_by_ai (AI draft published) | AI | S | extracted before/after sha256, flagged count, model |
| card.extracted_replaced_by_user (API) | user | S | before/after sha256 |
| knowledge_graph.rebuilt | system | S | digest before/after, cause |
| card.pdf_downloaded / json_exported / ontology_exported | user | S | format, digest, file sha256 |
| card_version.ontology_fetched (by step 2) | service | S | version, digest |
| ui: tab switched, node editor opened/cancelled, builder edits, import rows edited, risk/component rows typed | user | B | (unsaved work) |

## 2. Set control objectives (control-objectives)
| Event | Who | Obs | Key details |
|---|---|---|---|
| assessment.opened / started / reopened / start_refused / deleted | user | S | card version, card digest, risks; deletion snapshot |
| assessment.profile.inherited / switched / updated | user/system | S | profile version before/after, objectives dropped |
| risk.rated | user | S | impact and likelihood before/after, rating, band |
| risk.rating_comment.set / cleared | user | S | text before/after |
| ai.mapping.requested / completed / failed | user then AI | S | on_behalf_of, model, skill, profile version, prompt catalogue, per-risk objectives with quotes, findings, attempts |
| ai.model.resolved | AI | S | provider/model |
| mapping.risk.edited (manual) | user | S | objectives before/after, added (assessor) / removed (AI quote lost) |
| objective.key.set | user | S | key before/after (diff only) |
| scope.changed (what goes to step 4) | system | S | objectives before/after |
| objective_set.created / published / deleted | user | S | code, version n, content sha256 |
| objective.added / edited / retired / restored (draft) | user | S | fields before/after |
| objective_profile.created / version_saved | user | S | picks, pins, dropped |
| ui: chip pop-up opened, edit pop-up opened/cancelled, key ticked not saved | user | B | |

## 3. Identify tests and controls (catalogue, installs)
| Event | Who | Obs | Key details |
|---|---|---|---|
| catalogue.page.opened / tool_detail.opened | user | B (React app) | route, tool |
| catalogue.tool.created / updated (incl. status = review decision) / deleted (+ bulk) | user | S | before/after, reviewer |
| catalogue.metadata / tag / metric created/updated/deleted, tool.tag_added/removed | user | S | before/after |
| catalogue.package.uploaded / removed | user | S | wheel sha256, version, overwrite flag |
| catalogue.control.ingested / ingest_failed (AI turns a document into a checklist) | user then AI | S | file sha256, model, prompt/response sha256, questions sha256, auto-approved |
| catalogue.plugin.install_dispatched | user | B | package, version, target project |
| catalogue.install_info.served, catalogue.control.exported | service | S | package, version, package sha256 |
| plugin.installed (engine) | user | S | package, version, sha256, reused vs created, platform pid |
| control.installed (controls app) | user | S | checklist id, package sha256, questions |

## 4. Collect evidence (evidence page, engine, controls app)
| Event | Who | Obs | Key details |
|---|---|---|---|
| evidence.opened (version, carried offer) | user | S | card version, carried_from |
| evidence.links.saved | user | S | links added/removed, carried saved, refusals |
| ui.evidence.link_toggled (unsaved), version switched | user | B / S | |
| engine.project.bound / renamed, engine.component.created / updated / deleted | user | S | before/after, json_value sha256 |
| engine.component.file_uploaded / downloaded | user/worker | S | file sha256, size, previous file |
| engine.setting.created / updated (incl. secret rotation) / deleted | user | S | value sha256 (secret: rotated flag only) |
| engine.plugin.refreshed / disabled / toggled / configured / config_restored | user | S | config sha256, before/after |
| engine.config.exported / imported | user | B | file sha256 |
| engine.evaluation.run_requested / rejected | user | S | plugins, config sha256 each, inputs sha256, card version |
| engine.evaluation.status_changed / finalized / marked_failed | worker | S | before/after, on_behalf_of |
| eval.package.cached / plugin.inputs_fetched / config_materialised / venv_created / started / exited / finished / failed / siblings.revoked | worker | S | input and config sha256, versions, return code, log sha256 |
| engine.measures.recorded, engine.artifact.uploaded | worker | S | measures sha256, file sha256 |
| engine.results.viewed / artifact.previewed / downloaded | user | S | ids, file sha256 |
| controls.page.opened | user | S | route, checklist, submission |
| controls.checklist.questions_revised | user | S | questions before/after sha256 |
| controls.source.created | user | S | name, url |
| controls.submission.created / draft_saved / closed / reopened / archived / restored | user | S | answers sha256 before/after, version, score |
| controls.report.downloaded | user | S | PDF sha256 |

## 5. Analyse results (dashboard)
| Event | Who | Obs | Key details |
|---|---|---|---|
| dashboard.viewed, chart.data_queried, explore / SQL Lab / CSV export, admin chart or dashboard edits | user | S (Superset event logger) | dashboard, chart, query sha256, row count |
| dashboard.review_page.opened / left | user | S / B | time on page |
| dashboard.comments.viewed | user | S | |
| dashboard.comment.created / deleted | user | S | body sha256, chart snapshot (plot frozen) |
| dashboard.review.requested / resolved / edited (admin views) | user | S | status before/after, assignee |
| dashboard.project.registered / unregistered, session role sync | system | S | objects created/deleted, roles granted |

## 6. Compose the report
| Event | Who | Obs | Key details |
|---|---|---|---|
| report.page.opened / left | user | S / B | layout, unsaved flag |
| report.layout.created / imported / duplicated / updated / deleted / exported | user | S | blocks sha256 before/after, revision |
| report.preview.rendered | user | S | layout revision, card version, html sha256 |
| report.generated / failed / partial | user | S | snapshot fingerprint, document sha256, card version, block statuses, the ledger head it prints |
| report.downloaded / pdf_viewed | user | S | document sha256 |
| report.template.created / imported / updated / deleted / exported | user | S | look sha256, logo sha256 |
| renderer.render.served / superset_chart.fetched / comments.embedded | service | S | fingerprint, PNG sha256, comment ids |

## Gaps that block a trustworthy log (fix with or before the ledger)
1. Who acted is often unknown: CO handlers ignore the verified caller; qualification reads an
   unverified header claim and stores no author on cards, patches, links, retirements; the catalogue
   discards the caller; the engine logs workers as "unknown"; AI runs lose the user who asked.
2. History is destroyed today: controls question review cascade-deletes answers of closed
   submissions; deleting a report layout deletes its generated reports; a new AI mapping run deletes
   the assessor's own rows; the AI card draft, reviewer corrections and component links are
   overwritten; engine settings/files overwritten; catalogue hard deletes; dashboard comment deletes.
3. The two existing immudb tables are global (no project), the engine's verify() checks nothing,
   Superset logs numeric user ids and drops the event content.
4. AI prompts and responses are kept nowhere; the qualification agent's run result lives in memory.
5. Page left, unsaved edits, dialogs, install dispatch: browser only, need one shared beacon.
