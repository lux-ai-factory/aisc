# 02 Tests: failing tests for per-project LLM keys and model choice

Stage 2 of the pipeline in this folder. Every requirement of 01-specs.md is named by at least one
test (the ID is in the test name, or in the docstring for the pre-existing tests of S3.6). No
product code was written. Nothing touched the running stack: every database was a throwaway
postgres container, every provider and the platform were fake servers on 127.0.0.1, every key is
a random `sk-test-<hex>`.

## 1. Files

| repo | file | kind |
|---|---|---|
| top-level | `platform/tests/llm_support.py` | helper: FakeServer, session Fernet key, internal token |
| top-level | `platform/tests/test_llm_catalogue.py` | no DB, fake HTTP |
| top-level | `platform/tests/test_llm_store.py` | DB (throwaway) |
| top-level | `platform/tests/test_api_llm.py` | DB + TestClient |
| top-level | `scripts/tests/test_llm_keys.py` | static checks, secrets.sh on a scratch copy |
| top-level | `scripts/tests/test_compose.py` | 4 tests appended (S6.1, S6.2, S6.7) |
| apps/qualification | `services/agents/tests/fake_http.py` | helper |
| apps/qualification | `services/agents/tests/test_baf_llm.py` | A's copy of the shared cases |
| apps/qualification | `services/agents/tests/test_project_llm.py` | S3.7 |
| apps/qualification | `test/unit/FillerTrigger.test.ts`, `test/unit/cardVersionsInCoreSystem.test.ts` | S3.8 blocks appended |
| apps/control-objectives | `tests/fake_http.py` | helper (same as A's) |
| apps/control-objectives | `tests/test_baf_llm.py` | same cases as A's; only `MODULE`/`LEGACY` differ |
| apps/control-objectives | `tests/test_project_llm.py` | S3.9, S3.10 (DB) |

## 2. Requirement -> tests

Short names: CAT = platform/tests/test_llm_catalogue.py, STORE = platform/tests/test_llm_store.py,
API = platform/tests/test_api_llm.py, ABL = agents tests/test_baf_llm.py, BBL = control-objectives
tests/test_baf_llm.py (same test names as ABL), APL = agents tests/test_project_llm.py, BPL =
control-objectives tests/test_project_llm.py, KEYS = scripts/tests/test_llm_keys.py, COMPOSE =
scripts/tests/test_compose.py, FT = test/unit/FillerTrigger.test.ts, CV =
test/unit/cardVersionsInCoreSystem.test.ts.

| ID | tests |
|---|---|
| S1.1 | STORE::test_s1_1_schema_llm_is_owned_by_platform_rw_and_closed_to_everyone_else |
| S1.2 | STORE::test_s1_2_llm_provider_has_exactly_the_specified_columns, test_s1_2_the_provider_id_is_checked[*] |
| S1.3 | STORE::test_s1_3_llm_system_choice_has_exactly_the_specified_columns, test_s1_3_system_and_model_are_checked_and_the_provider_is_restricted |
| S1.4 | STORE::test_s1_4_the_template_file_exists_and_is_idempotent_sql, test_s1_4_applying_the_file_again_changes_nothing |
| S1.5 | STORE::test_s1_5_a_new_project_gets_the_llm_tables_at_creation, test_s1_5_a_project_made_before_0005_gets_it_at_the_first_query_after_start, test_s1_5_deleting_a_project_drops_its_keys_with_its_database |
| S1.6 | STORE::test_s1_6_module_roles_cannot_read_the_llm_tables[controls_rw, dashboard_ro, report_ro], test_s1_6_the_inspector_reads_only_ciphertext |
| S2.1 | API::test_s2_1_a_member_who_is_not_an_admin_gets_403_on_every_llm_route, test_s2_1_a_stranger_gets_404_on_every_llm_route, test_s2_1_an_unknown_project_is_404_even_for_an_admin, test_s2_1_the_project_may_be_named_by_slug_or_pid |
| S2.2 | API::test_s2_2_an_unauthenticated_call_is_401 |
| S2.3 | CAT::test_s2_3_the_catalogue_is_exactly_the_agents_thirteen_providers, test_s2_3_every_entry_has_a_label_and_the_two_flags; KEYS::test_s3_1_s2_3_the_agents_providers_are_the_platform_catalogue |
| S2.4 | API::test_s2_4_the_listing_has_every_provider_and_both_systems |
| S2.5 | API::test_s2_5_usable_follows_key_and_base_url, test_s2_5_ollama_defaults_to_host_docker_internal, test_s2_5_ollama_default_comes_from_platform_ollama_base_url |
| S2.6 | API::test_s2_6_s5_1_no_page_facing_response_holds_the_key_or_its_ciphertext |
| S2.7 | API::test_s2_7_saving_a_key_answers_the_provider_entry, test_s2_7_an_absent_key_keeps_the_stored_one, test_s2_7_a_new_key_replaces_the_old_one, test_s2_7_an_empty_base_url_clears_it, test_s2_7_a_base_url_for_a_hosted_provider_is_422, test_s2_7_an_empty_body_is_422, test_s2_7_an_unknown_provider_is_404 |
| S2.8 | API::test_s2_8_a_malformed_key_is_422_with_a_fixed_message[*], test_s2_8_surrounding_whitespace_is_stripped_and_4096_characters_accepted |
| S2.9 | API::test_s2_9_a_bad_base_url_is_422[*], test_s2_9_a_good_base_url_is_stored[*] |
| S2.10 | API::test_s2_10_deleting_a_stored_key_is_204_and_removes_the_row, test_s2_10_deleting_nothing_is_404, test_s2_10_deleting_a_key_a_system_uses_is_409_naming_it |
| S2.11 | API::test_s2_11_without_platform_secrets_key_a_key_write_is_503, test_s2_11_a_malformed_platform_secrets_key_is_503[*], test_s2_11_the_catalogue_still_answers_without_the_secrets_key, test_s2_11_s2_25_a_resolve_that_needs_a_key_is_503_without_the_secrets_key; STORE::test_s5_2_s2_11_only_fernet_ciphertext_is_stored, test_s2_11_the_newest_key_encrypts_and_older_ones_still_decrypt |
| S2.12 | API::test_s2_12_an_unreadable_key_is_reported_by_models_and_resolve |
| S2.13 | STORE::test_s2_13_rotate_re_encrypts_every_key_and_prints_counts_only |
| S2.14 | API::test_s2_14_a_key_sent_as_a_number_is_422_without_the_value, test_s2_14_a_non_json_body_is_422_without_the_value, test_s2_14_a_validation_error_elsewhere_drops_input_and_ctx_too |
| S2.15 | API::test_s2_15_models_are_listed_live_with_the_stored_key, test_s2_15_a_failing_provider_is_200_with_an_error, test_s2_15_a_provider_that_is_not_usable_is_409, test_s2_15_an_unknown_provider_is_404, test_s2_15_ollama_lists_from_the_stored_base_url |
| S2.16 | CAT::test_s2_16_a_refused_key_is_named_with_its_status[401,403], test_s2_16_another_status_is_reported_without_the_body[*], test_s2_16_a_provider_that_is_down_could_not_be_reached, test_s2_16_not_json_or_the_wrong_shape_is_not_a_model_list[*], test_s2_17_s2_16_a_slow_provider_times_out_with_a_fixed_message |
| S2.17 | CAT::test_s2_17_ids_are_deduplicated_sorted_and_bad_ones_dropped, test_s2_17_at_most_5000_ids_are_kept, test_s2_17_at_most_ten_pages_are_fetched, test_s2_17_a_page_over_5_mb_is_not_a_model_list, test_s2_17_s5_6_redirects_are_not_followed_so_the_key_stays_with_the_provider, test_s2_17_s2_16_a_slow_provider_times_out_with_a_fixed_message |
| S2.18 | CAT::test_s2_18_s2_19_each_hosted_provider_lists_from_its_constant_documented_url, test_s2_18_no_env_variable_overrides_a_hosted_url |
| S2.19 | CAT::test_s2_19_openai_style_providers_send_a_bearer_key_and_read_data_ids[openai, deepseek, groq, meta, openrouter, qwen, xai], test_s2_19_anthropic_uses_x_api_key_and_pages_by_after_id, test_s2_19_mistral_keeps_only_chat_models_when_capabilities_are_given, test_s2_19_google_uses_its_header_never_the_query_and_strips_the_prefix, test_s2_19_together_reads_a_top_level_list_of_chat_and_language_models, test_s2_19_ollama_lists_tags_under_the_base_url_without_v1_and_without_auth, test_s2_19_compatible_lists_base_url_models_with_a_bearer_when_a_key_is_stored, test_s2_19_compatible_without_a_key_sends_no_authorization_and_accepts_a_bare_list |
| S2.20 | API::test_s2_20_a_choice_is_saved_and_shown (also D6: no provider call), test_s2_20_an_unknown_system_is_404, test_s2_20_an_unusable_provider_or_bad_model_is_422[*], test_s2_20_choosing_ollama_makes_its_keyless_row |
| S2.21 | API::test_s2_21_removing_a_choice_goes_back_to_the_environment |
| S2.22 | API::test_s2_22_the_project_must_be_a_pid, test_s2_22_an_unknown_system_or_project_is_404 |
| S2.23 | API::test_s2_23_s5_5_a_missing_or_wrong_token_is_401, test_s2_23_without_platform_internal_token_the_route_is_closed[unset, empty], test_s2_23_the_token_is_compared_in_constant_time |
| S2.24 | API::test_s2_24_s5_5_a_request_that_came_through_caddy_is_404[X-Forwarded-For, X-Forwarded-Host] |
| S2.25 | API::test_s2_25_no_choice_is_not_configured, test_s2_25_s5_1_a_choice_resolves_with_its_decrypted_key, test_s2_25_ollama_resolves_with_the_default_base_url_and_no_key, test_s2_25_compatible_resolves_with_its_stored_base_url, test_s2_25_a_choice_whose_key_is_gone_is_409_naming_the_provider, test_s2_11_s2_25_a_resolve_that_needs_a_key_is_503_without_the_secrets_key |
| S2.26 | API::test_s2_26_the_resolve_answer_is_not_cached |
| S3.1 | KEYS::test_s3_1_both_copies_exist_and_are_byte_identical, test_s3_1_it_imports_only_the_standard_library_and_baf, test_s3_1_s2_3_the_agents_providers_are_the_platform_catalogue |
| S3.2 | ABL/BBL::test_s3_2_providers_and_optional_key_moved_unchanged, test_s3_2_the_two_systems, test_s3_2_llm_config_is_frozen_with_optional_key_and_base_url, test_s3_2_s5_3_llm_config_never_shows_its_key, test_s3_2_config_from_env_* (5 tests), test_s3_2_resolve_error_is_a_runtime_error |
| S3.3 | ABL/BBL::test_s3_3_* (9 tests: unknown provider, missing key, property store, ollama base URL, compatible needs base URL, placeholder key, own agent per build, never writes os.environ, completer) |
| S3.4 | ABL/BBL::test_s3_4_* (10 tests: no project, unconfigured platform x2, token header, configured answer, 404/409/401/503 fail closed, bad JSON, env timeout, timeout argument, platform down) |
| S3.5 | ABL/BBL::test_s3_5_the_platform_choice_wins, test_s3_5_no_choice_uses_the_fallback_then_the_environment, test_s3_5_d4_a_failing_platform_is_never_replaced_by_the_environment |
| S3.6 | pre-existing, unchanged and passing: agents tests/test_llm.py (19), control-objectives tests/test_llm.py, test_server.py, test_config.py, test_service.py |
| S3.7 | APL::test_s3_7_the_project_is_passed_to_the_run_and_recorded, test_s3_7_a_project_that_is_not_a_uuid_is_422_and_starts_nothing, test_s3_7_no_project_is_todays_behaviour, test_s3_7_fill_one_uses_the_projects_resolved_model, test_s3_7_fill_one_without_a_project_uses_the_environment, test_s3_7_a_project_with_no_choice_uses_the_environment, test_s3_7_d4_a_resolve_error_fails_the_run_with_the_platforms_reason, test_s3_7_s5_3_a_build_error_fails_the_run_without_the_key |
| S3.8 | FT: "S3.8 posts ?project=<pid> when a project id is given", "S3.8 encodes the project id", "S3.8 still never throws, reports refusals, and makes no call without a URL", "S3.8 requestFill passes the project id through"; CV: "S3.8 createFromForm returns the platform pid of the version's project", "S3.8 the action asks for the fill with the project id" |
| S3.9 | BPL::test_s3_9_map_uses_the_mapper_of_the_records_project_and_records_its_label, test_s3_9_d8_without_mapper_for_the_fixed_mapper_and_label_are_used, test_s3_9_d8_build_app_keeps_the_startup_model_label, test_s3_9_no_choice_on_the_platform_falls_back_to_the_startup_config, test_s3_9_s3_11_the_projects_choice_reaches_the_model, test_s3_9_d4_a_failing_platform_is_not_replaced_by_the_startup_model |
| S3.10 | BPL::test_s3_10_the_api_answers_502_with_the_reason_and_saves_nothing[resolve, build], test_s3_10_the_form_route_answers_502_plain_text_and_saves_nothing |
| S3.11 | ABL/BBL::test_s3_11_a_resolved_compatible_config_sends_its_key_and_model; BPL::test_s3_9_s3_11_the_projects_choice_reaches_the_model; APL::test_s3_7_fill_one_uses_the_projects_resolved_model |
| S4.1 | KEYS::test_s4_1_the_page_has_the_launchers_look_and_one_inline_script |
| S4.2 | KEYS::test_s4_2_the_manage_menu_links_the_page_for_admins_only (working tree only, R5) |
| S4.3 | KEYS::test_s4_3_non_admins_are_told_and_no_llm_call_is_made_first |
| S4.4 | KEYS::test_s4_4_key_fields_are_write_only_password_inputs |
| S4.5 | KEYS::test_s4_5_systems_offer_usable_providers_and_live_models |
| S4.6 | KEYS::test_s4_6_errors_come_from_detail_or_error_and_a_dead_platform_is_said_plainly |
| S4.7 | KEYS::test_s4_7_csp_and_injection_safe |
| S4.8 | KEYS::test_s4_8_the_page_never_puts_anything_but_empty_into_a_key_field |
| S5.1 | API::test_s2_6_s5_1_no_page_facing_response_holds_the_key_or_its_ciphertext, test_s2_25_s5_1_a_choice_resolves_with_its_decrypted_key |
| S5.2 | STORE::test_s5_2_s2_11_only_fernet_ciphertext_is_stored, test_s1_6_the_inspector_reads_only_ciphertext |
| S5.3 | CAT::test_s5_3_listing_never_logs_the_key_on_success_or_any_error; API::test_s5_3_no_key_reaches_the_logs; ABL/BBL::test_s5_3_building_and_predicting_log_no_key, test_s3_2_s5_3_llm_config_never_shows_its_key; APL::test_s3_7_s5_3_a_build_error_fails_the_run_without_the_key |
| S5.4 | API::test_s5_4_a_key_of_one_project_is_nothing_in_another |
| S5.5 | API::test_s2_23_s5_5_*, test_s2_24_s5_5_*; KEYS::test_s6_4_*; COMPOSE::test_s6_7_* (platform publishes no port) |
| S5.6 | CAT::test_s2_17_s5_6_redirects_are_not_followed_so_the_key_stays_with_the_provider, test_s5_6_a_hosted_provider_ignores_any_base_url_it_is_given |
| S5.7 | API::test_s5_7_a_put_that_is_not_json_changes_nothing, test_s5_7_the_platform_has_no_cors_middleware |
| S5.8 | CAT::test_s5_8_admin_urls_are_fetched_without_redirects_and_never_reflected[ollama, compatible], test_s5_8_admin_urls_get_the_same_size_bound[ollama, compatible] |
| S6.1 | COMPOSE::test_s6_1_platform_gets_the_two_secrets_and_the_ollama_default |
| S6.2 | COMPOSE::test_s6_2_the_card_agent_reaches_the_platform_with_the_token, test_s6_2_the_risk_mapper_gets_the_token |
| S6.3 | KEYS::test_s6_3_a_new_install_gets_both_secrets_and_a_second_run_keeps_them, test_s6_3_an_existing_install_gets_them_appended_without_replacing_anything |
| S6.4 | KEYS::test_s6_4_the_launcher_answers_404_to_api_internal_before_proxying_api |
| S6.5 | KEYS::test_s6_5_the_platform_depends_on_httpx_and_cryptography_at_runtime, test_s6_5_the_agents_need_nothing_new |
| S6.6 | KEYS::test_s6_6_env_files_say_where_the_two_secrets_come_from[env.development, env.staging] |
| S6.7 | COMPOSE::test_s6_7_the_compose_files_stay_valid_with_the_new_variables (plus the existing test_s6a_compose_config_is_valid) |

## 3. How to run each suite

Throwaway Postgres (never 5432, removed afterwards). Compared with 01-specs section 8, two more
init files are applied so S1.6 can test `report_ro` and `inspector_ro` (the tests skip a role
that is missing):

```
cd /home/listuser/aisc-install
NAME=aisc-t-llmkeys-$(openssl rand -hex 4); PW=$(openssl rand -hex 12)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
[ "$PORT" != 5432 ] || exit 1
docker run --rm -d --name $NAME -p 127.0.0.1:$PORT:5432 -e POSTGRES_USER=aisc-postgres-user \
  -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=platform postgres:14-alpine
until docker exec $NAME pg_isready -U aisc-postgres-user -d platform; do sleep 1; done; sleep 2
for f in platform-db project-databases inspector-role report-roles; do
  docker exec -i $NAME psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 -q < init/$f.sql; done
# ... suites below ...
docker rm -f $NAME
```

| suite | command |
|---|---|
| platform | from `platform/`: `PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform PLATFORM_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform uv run --extra dev pytest -q -p no:cacheprovider` |
| A (agents) | from a scratch directory (see note): `A=/home/listuser/aisc-install/apps/qualification/services/agents; uv run --no-project --with-requirements $A/requirements.txt --with pytest --with httpx --with rdflib python -m pytest -q -p no:cacheprovider -c $A/pytest.ini --rootdir $A $A/tests` |
| B (control-objectives) | from `apps/control-objectives`: `CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test uv run --extra dev pytest -q -p no:cacheprovider` |
| qualification-web | from `apps/qualification`: `npx vitest run test/unit/FillerTrigger.test.ts test/unit/cardVersionsInCoreSystem.test.ts && npx tsc --noEmit` |
| top-level | from the repo root: `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_llm_keys.py scripts/tests/test_compose.py` |

Notes on the A command, both pre-existing and unrelated to this feature:
- BAF writes `application.log` into the working directory, and
  `apps/qualification/services/agents/application.log` is owned by root (an earlier `docker run`),
  so running from that directory fails at collection with PermissionError. Running from a scratch
  directory with `-c`/`--rootdir` avoids it without touching the file.
- `tests/test_controls.py::TestEveryFindingIsPublishable` imports the ontology builder, which needs
  `rdflib`; without `--with rdflib` it fails (baseline 99 passed, 1 failed).
- The host runs a real ollama on 127.0.0.1:11434. No test may reach it: APL clears every provider
  variable (autouse) and points the fail-closed test's ollama at a closed port.

## 4. Observed results (2026-09-24, throwaway container aisc-t-llmkeys-1be7c433, removed)

| suite | baseline before stage 2 | with the new tests | new tests red | new tests already green (guards) |
|---|---|---|---|---|
| platform | 110 passed, 2 skipped | 100 failed, 47 errors, 111 passed, 2 skipped | 147 | 1: test_s5_7_the_platform_has_no_cors_middleware |
| A (agents) | 100 passed | 7 failed, 38 errors, 101 passed | 45 | 1: test_s3_7_no_project_is_todays_behaviour |
| B (control-objectives) | 250 passed, 1 skipped | 4 failed, 42 errors, 251 passed, 1 skipped | 46 | 1: test_s3_9_d8_without_mapper_for_the_fixed_mapper_and_label_are_used |
| qualification-web (2 files) | 19 passed | 5 failed, 20 passed; tsc clean | 5 | 1: "S3.8 still never throws..." |
| top-level (2 files) | 4 passed | 21 failed, 5 passed | 21 | 1: test_s6_5_the_agents_need_nothing_new |

Every pre-existing test still passes. The reasons for red, checked by grouping the failure lines:
- "errors" are fixture-setup failures: `ModuleNotFoundError: No module named
  'platform_service.llm_catalogue'` (47, CAT and API's `cat` fixture), `'fill.baf_llm'` (38),
  `'aisc_control_objectives.baf_llm'` (42). The modules are imported inside fixtures on purpose so
  a missing module fails each test instead of stopping collection of the whole suite.
- platform failures: routes missing (`404 {"detail":"Not Found"}`, `assert 404 == 200/422/503`),
  `relation "llm.provider" does not exist`, `schema llm` absent, `0005_llm.sql` missing, no
  `compare_digest` in the source.
- A: `fill_one() got an unexpected keyword argument 'project'`, run state has no `project` or
  `model`, `?project=not-a-pid` accepted (202), the D4 run failed on the env model ("Connection
  error.") instead of the platform's reason.
- B: `Projects.__init__() got an unexpected keyword argument 'mapper_for'`, build_app gives Projects
  no `mapper_for`.
- qualification-web: URL has no `?project=`, createFromForm returns `{id}` only, requestFill called
  without the pid.
- top-level: `baf_llm.py` and `homepage/llm.html` missing, no `llm-settings` link, secrets.sh
  writes neither new secret, no Caddy block, pyproject/uv.lock unchanged, env comments missing,
  compose variables missing.

Tests that could have passed for the wrong reason were tightened: every 404 test first proves the
route exists (a 200 on the same route) or requires a `detail` other than the router's "Not Found".

## 5. Interfaces these tests pin (decisions for stage 3/4)

The spec made module names binding and left some names open. The tests fix them as follows:
- T1 `llm_catalogue.PROVIDERS` is a mapping id -> entry; an entry may be a dict or an object and has
  `label`, `key_required`, `base_url_editable`, `lister` (any truthy kind name).
- T2 `llm_catalogue.MODELS_URL: dict[str, str]` holds the 11 hosted listing URLs (exact values of
  S2.19, without query strings), read at call time so tests can `monkeypatch.setitem` it. This is
  "the constant" of S2.18.
- T3 `llm_catalogue.list_models(provider, api_key=None, base_url=None) -> {"models", "error"}`.
  Timeout env `PLATFORM_LLM_LIST_TIMEOUT` is read at call time; the message prints the configured
  number (`1 s` or `1.0 s` accepted).
- T4 Redirect answers are reported as `"<label> answered HTTP <3xx>"` (S2.16 "other HTTP status").
- T5 Env `PLATFORM_SECRETS_KEY`, `PLATFORM_INTERNAL_TOKEN`, `PLATFORM_OLLAMA_BASE_URL` are read per
  request, not at import (tests monkeypatch them).
- T6 404s from the llm routes and the resolve route (unknown project, provider, system, nothing to
  delete) carry a specific `detail`, not the router's "Not Found".
- T7 S2.11 malformed key covers both a non-Fernet value and a list with one bad member.
- T8 `llm_store` has a `__main__` entry: `python -m platform_service.llm_store rotate`, using
  `PLATFORM_DATABASE_URL` and `PLATFORM_SECRETS_KEY`, exit 0, stdout with counts only.
- T9 A's service: `POST /fill/{id}?project=<uuid>`; the run state carries `project` (null when
  absent). The existing test_service.py fakes take only `qualification_id`, so when `project` is
  absent the service must still call `fill_one(qualification_id)` without a `project` keyword (or
  stage 4 must accept changing those fakes; the spec says existing tests stay unchanged, so the
  first). `fill_one` returns `"model": "<provider>/<model>"`.
- T10 B: `Projects(..., mapper_for=callable)` keyword; S3.10 treats both `baf_llm.ResolveError` and
  `ValueError` raised by `mapper_for` as 502 (the build error of S3.3 is a ValueError).
- T11 In `LlmConfig`, equality is dataclass equality (tests compare with `==`).

## 6. Spec gaps and contradictions found, with the decision taken

- G1 S1.1 says "no USAGE for any other role" and S1.6 says `inspector_ro` reads through
  `pg_read_all_data`. Not a contradiction: `pg_read_all_data` bypasses schema USAGE. The test
  checks the schema ACL names only `platform_rw` and that `has_schema_privilege` is false for
  `controls_rw` and `dashboard_ro`.
- G2 S1.6 needs `report_ro` and `inspector_ro`, which the spec's throwaway recipe (two init files)
  does not create. Decision: the recipe applies `init/inspector-role.sql` and
  `init/report-roles.sql` too; the tests skip a role that cannot connect.
- G3 S2.13 does not say what rotation does with a row no configured key decrypts. Not tested; the
  test runs on a database where every row is under the session key. Stage 4 should count such rows
  as "unreadable" and not abort the others (suggestion, not pinned).
- G4 S2.25 "choice whose key is missing" cannot happen through the API (D7 refuses the delete). The
  test makes it by setting `ciphertext = NULL` in SQL.
- G5 S5.7 "no CORS middleware" is true today, so its guard test is green now; the non-JSON PUT test
  is red only because the route and listing are missing.
- G6 S3.6 needs no new test: the existing A and B tests are the proof and stay unchanged.
- G7 S4.x are static regex checks, as the spec says; they cannot prove runtime behaviour (loading
  text, preselection). S4.2 can pass only on the working tree (R5): `homepage/project.html` has
  the user's uncommitted edit and was not touched here.
- G8 S6.3 is tested on a scratch copy (scripts/secrets.sh, keycloak/aisc-realm.json,
  env.plugin_downloader copied to a tmp dir); the test also asserts the repo's `env.runtime` mtime is
  unchanged.
- G9 S2.19 `ollama`: "base_url without a trailing /v1" is tested with a stored URL ending in `/v1`;
  a stored URL without it (the default) is tested through the API (S2.15 ollama test).

## 7. Commits

Test files only, by explicit path, on `feat/unified-modules`; nothing pushed. The top-level commit
does not bump the submodule pointers (the new test commits in apps/qualification and
apps/control-objectives stay unrecorded at top level until stage 4 records them with the code).
See PROGRESS.md for the hashes.
