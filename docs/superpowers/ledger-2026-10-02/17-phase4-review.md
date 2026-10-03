**Verdict: 1 blocker, 6 majors, 18 minors. Phase 4 is not done yet.** The security core holds up. The read routes are member-only, the export is for owners and admins only, the per-entry verification is real, the export checker rejects an edited and re-hashed file, the internal route never lets a caller name a person, and the beacon never writes to immudb. What keeps the phase open: the panel can't be reached in a browser (B1), the index check can be dodged by deleting or editing the columns it doesn't compare (M1), and a few guarantees the spec states are missing in code (I3 on the internal route, the T21 record, D10 retention).

## What I checked

Phase 4 is commits b44e7d0 and 430e6eb on feat/unified-modules (HEAD 790bf57 only adds the phase 3 drills). I made no commits, pushed nothing, and touched nothing on the live stack. I used my own throwaway Postgres and immudb (`aisc-t-rev10-*`, `docker run`, not compose), and never used 5432.

**The working tree is not phase 4.** When I started, someone had uncommitted S9 work in progress in the repo checkout: `store.py`, `export.py`, `app.py` (the 501 branch removed), `verify-ledger-export.py`, a new `immudb_proof.py`, tests and the spec. Running the phase 4 tests in that checkout gave 9 failures, all in the new S9 immudb export tests. A `git checkout` revert there would have destroyed that work. So I reviewed and mutated an exact copy of 790bf57 (`git archive`) in my scratchpad, and left the checkout alone apart from this file. Every finding below is against the committed code. File:line references point to 790bf57. While I was reviewing, that work landed as dc47757 (S9) and db20318 (drills). I have not reviewed either. m8, m9 and the 501 part of m18 may be superseded by dc47757. The other findings sit in code that S9 doesn't touch (S9 changed `export.py`, the stores and the checker; M6 still needs checking against the new checker).

- **Phase 4 suites on the committed copy** (`LEDGER_TESTS_REQUIRED=1`, real Postgres and immudb): `test_ledger_{routes,internal,beacon,export_checker,failure,privacy}.py` gave 68 passed, 0 skipped. `scripts/tests/test_ledger_pages.py` gave 7 passed (node present, so the parse checks ran).
- **Probes.** I wrote 17 probe tests (scratchpad only, never in the repo), each asserting the current behaviour a finding describes. All of them passed, which means every behaviour below was reproduced, not just inferred.
- **Mutations.** Listed in the last section. Each one was applied to the scratchpad copy, the named tests were run, and the file was restored byte for byte from `git show 790bf57:<path>`, then diffed to confirm.
- **Read only:** the Caddyfile launcher block, spec 3.5, 4.4, 6.2, 6.3, 7.3 to 7.5, S9, and test plan rows A1-A4, I1-I3, B1-B2.

## Blocker

**B1. The Activity log and the export link never appear in a browser.** `Caddyfile:221` answers `handle /api/authz/* { respond 404 }` on the launcher, ahead of `handle_path /api/*`. That rule came in with phase 2, for T18. But every page asks for the caller's role at `/api/authz/projects/{slug}`: `homepage/project.html:488` (the Manage menu), `homepage/logs.html:201` (the export link), and also `llm.html` and `connections.html`. Through the real gateway, that fetch gets 404, so `a` is null.
- `project.html` returns early, so no member sees the menu or the new "Activity log" link.
- `logs.html` never un-hides "Export for an auditor", even for an owner or an admin.
- The `page.opened` beacon in `project.html:496` sits inside that same callback, so it never fires either.

The page tests only grep the HTML, and the gateway tests never request `/api/authz/projects/*`, so nothing catches it. Phase 4's done-when ("the record-to-enforce flip in a browser on every app") can't be met as things stand. Phase 2 is unpushed and not deployed, so this is latent, not live.
*Fix:* narrow the launcher block to the witness and Caddy's own checks (`/api/authz/witness`, `/api/authz/admin`, `/api/authz/schema`), or move the role route to a path outside `/authz/` (for example `/api/projects/{slug}/me`). Add a real-caddy gateway test: a member's `GET /api/authz/projects/<slug>` through the launcher answers 200, and `/api/authz/witness` still answers 404.

## Majors

**M1. The index check misses deleted rows and the columns that filters use (T12).** `app.py:1500` compares 13 columns, but not `occurred_at`, `actor_kind` or `project_pid`. The `from`/`to` filters (`app.py:1592`) and the `ai` filter (`app.py:1590`) run on exactly those unverified columns, and nothing compares the set of index rows with the log.
- *Reproduced, case 1:* delete one `ledger.event_index` row. The list answers 200 and the entry is gone, with no alarm.
- *Reproduced, case 2:* set a person's row to `occurred_at='2000-01-01'`, `actor_kind='ai'`. The unfiltered list shows no alarm, `?from=2026-01-01` hides the row, and `?ai=true` shows the person's action as the AI's.

T12 says the index can't be used "to hide or change events". Comparing columns only covers rows that are actually shown. Anyone with write access to the platform database can quietly drop an entry from the panel.
*Fix:*
- add `occurred_at` (compared as instants), `actor_kind` and `project_pid` to `_INDEXED`;
- for each page, check that the shown seqs plus the filtered-out seqs account for every seq between the store's head and the cursor (cheapest: for an unfiltered page, require contiguous seqs from `head` downward, and raise an alarm on a gap);
- in `verify()`, compare the index's seq set and count for the log with `store.head(log).seq`, and report missing or extra rows as a reconciliation alarm.

**M2. The internal route silently drops a re-send with different content (I3).** `app.py:1783` does `SELECT 1 FROM core.outbox WHERE event_id = %s` and, if the id is already there, answers 202 `queued` without comparing anything. `core.outbox` rows are kept after delivery, so this holds for ever. *Reproduced:* the same `event_id` with another `item_id` and `model` gives 202 twice, the outbox keeps the first, and after the relay no `duplicate_event_id` is recorded. I3 says "never silently dropped". The check also ignores the emitter: an engine-token post that reuses an agents event id gets 202 (reproduced). Two concurrent first posts race to a `UniqueViolation` and a 500.
*Fix:* `INSERT ... ON CONFLICT (event_id) DO NOTHING RETURNING`. On conflict, compare the stored row (emitter, project, the digest of what was sent) with the new one. Equal means 202 replay. Different means a `ledger.rejected` / `duplicate_event_id` record (or a 409 plus an alarm). Never a silent 202.

**M3. A re-anchor can happen with no record (T21).** `app.py:1691` resets the trusted state first (`store.reanchor`), then `store.append(PLATFORM_DB, ...)` at `app.py:1702`, outside the `try`. After an immudb restore, the platform log is very likely rolled back too, and that append raises `TamperAlarm`. *Reproduced (memory store):* both logs rolled back. The admin's POST gives 500, the project's verified state is already moved to the server's, and the platform log gains nothing. T21 says the `ledger.reanchored` entry is "the only way forward", and here the way forward is taken without it. On immudb, `ImmudbLedger.reanchor` (`store.py:464`) also returns `new = 0`, so even a recorded entry doesn't name the new head (spec: "naming both heads"). The memory store returns a seq while immudb returns a tx id, so the units differ too.
*Fix:*
- record first, re-anchor second: build the entry with the head the admin is about to trust, append it, then reset the state. If the platform log can't take it, answer 409/503 and change nothing;
- on immudb, read the server's current state (tx id and hash) without trusting it yet, and record both old and new as `{tx_id, tx_hash}`;
- have the admin send the `expected_head` they checked, and refuse if the server's differs. Otherwise there is a gap between "admin looked" and "platform trusts" (trust on first use);
- take the project's `_log_lock(log)` around the reset;
- add a way, or a runbook step, for a restored platform log, since `ReanchorIn` only takes project pids.

**M4. Page views are never expired (D10, I10).** `pageviews.expire` (`pageviews.py:45`) has no caller outside `test_page_views_expire`: no scheduler, no relay hook, no CLI. `ledger.page_view` grows for ever, holding per-person browsing times (a pseudonym, but linkable through the mapping) past the 90 days the DPIA will promise. Test B1 shows that `expire()` works, not that retention happens.
*Fix:* call `expire(PAGE_VIEW_RETENTION)` from the relay's loop or from a daily job the platform starts, and test that the job is wired up (for example, that the scheduler's registered tasks include it).

**M5. One oversized event stalls a project's whole log.** The internal route sets no size limit on the body or on any field. `agent.run_failed` allows `details.error` as free text, and `item_id`, `model` and `item_version` are free strings. A legitimate agent that puts a long traceback in `error` produces an entry over `MAX_ENTRY_BYTES`. `_deliver_event` doesn't catch `EntryTooLarge` (only `LedgerUnavailable`/`UnknownDatabase`, `relay.py:138`), and `relay_once` turns it into `pending`. The item sorts first again on every pass, so every later event of that project waits for ever. *Reproduced:* a 72 KB `error` on a real run, then a normal `card.augmented_by_ai`. Three relay passes raise `EntryTooLarge` each time, and the later event is never delivered. The relay owns this code path (phase 3), but phase 4's route is the new way in from the services that T17 treats as less trusted.
*Fix:* in the relay, treat `EntryTooLarge` as a rejection (`ledger.rejected`, reason `too_large`; the rejected entry is small). In the route, refuse with 413 a body over a cap, and with 422 any string field over a few hundred bytes (`item_id`, `model`, `item_version`, each details value).

**M6. The checker passes files it should refuse, and its "ok" says more than it checked.** `scripts/verify-ledger-export.py:94-161`:
- *Duplicate keys.* `json.loads` keeps the last of two equal keys. *Reproduced:* changing `"item_id":"r1"` into `"item_id":"FORGED","item_id":"r1"` still gives exit 0. A spreadsheet or another first-wins parser the auditor opens the file with shows `FORGED`. Fix: `object_pairs_hook` that refuses duplicate keys, and `parse_constant` that refuses NaN and Infinity.
- *Content unchecked by default.* Without `--check-content`, a forged `content` line still prints `ok: ... signed` (reproduced). Fix: check content by default (opt out with a flag), or print "content NOT checked" and exit with a distinct code.
- *Unsigned parts.* The output never names the log or the project, so a validly signed export of another project passes as this one. Unknown top-level fields on a line pass too (reproduced). Fix: print `head.log` and the entries' `project_pid`, add a required `--log` or `--project`, refuse unknown fields, and refuse entries whose `project_pid` differs from the first one.

I rate this major because R4.9's point is that an auditor can rely on exit 0.

## Minors

- **m1. Bad filter values give 500.** `?step=abc`, `?from=notadate` and `?card_version=x` all reach Postgres and answer 500 (reproduced). Fix: validate, and answer 422.
- **m2. The internal route lets the caller choose `outcome`** (`app.py:1790`). *Reproduced:* an accepted AI event logged with `outcome="refused"`, which the panel shows in red as a refusal. Fix: allow only an enum from emitters (`ok`, `failed`), and keep `refused` for the relay.
- **m3. Equal caller tokens aren't refused.** `system_of_token` keeps the last match, so with two variables holding one value, the engine's events are filed as `dashboard`'s (reproduced). `/internal/.../llm` refuses equal tokens with 503, and this route should too. The ledger tokens also have no old-and-new overlap (T22, `ROTATION_OVERLAP`).
- **m4. 401 versus 503 on the internal route.** With any caller unset, every wrong token gets 503 "isn't configured for every caller". That is harmless (backend network only, `X-Forwarded-*` refused), but it tells a prober about configuration. Answering 401 to a wrong token in all cases, and logging the misconfiguration, is simpler.
- **m5. The beacon rate limit is per person per project, not per person** (`app.py:1843`, `count_recent(ref)` with a project-scoped ref). *Reproduced:* 120 beacons in a minute across two projects, all 204. The count-then-insert also races. Spec 6.3 says "per person". Fix: count on the platform-scope ref, or in a small per-subject counter.
- **m6. Beacon detail values aren't checked.** The keys are, but `page` can be any nested object, and a `Bearer eyJ...` string is stored (reproduced). The registry's `_holds_secret` and a string-only rule should apply. No page shows `page_view` yet, so there is no stored XSS today. Any future viewer must use textContent, as `logs.html` does.
- **m7. The beacon reads the whole body before the 2 KB check** (`app.py:1807`, `await request.body()`). The caller is authenticated first, but a large body still lands in memory. Fix: stream with a limit, or rely on a Caddy `request_body max_size` for `/api/ledger/beacon`, and say which one is relied on.
- **m8. `MemoryLedger.export_head` signs any prefix** (`store.py:223`: `0 <= seq < len(chain)`). *Reproduced:* it signs a head at seq 1 of a 3-entry log. The route always passes the full length, so this isn't reachable today, but the store's contract should refuse a short head. The uncommitted S9 work already tightens it.
- **m9. On immudb, the 501 comes only after the whole log has been read** (`export.py:25`). Every entry is fetched and verified, then `export_head` raises. That is safe (nothing is returned and no key leaves), but it's a costly way to say "not implemented". Check `hasattr`/capability first. The 501 itself is right: no unverifiable file reaches an auditor. The working tree currently removes that `except NotImplementedError` branch along with the S9 work, so it must not land without the immudb export.
- **m10. Spec 6.3 gaps.**
  - `events/{seq}` doesn't include the witness record.
  - `/ledger/projects` has no "last verification, alarms".
  - `POST /projects/{slug}/ledger/verify` doesn't exist.
  - Only `page.opened` is ever sent: no page sends `page.left`, `dialog.cancelled` or `unsaved_changes`.
  - The beacon script is only on the launcher pages, but the plan says "beacon on each site".

  Each one should be built, or moved to a named later phase in the coding plan.
- **m11. `logs.html` mixes filter states.**
  - "Older entries" uses the cursor from the last loaded filter with the form's current values. Changing a filter without pressing Filter and then paging mixes the two.
  - On an error with `reset`, the old rows stay under the ALARM line, so a 409 for a new filter still shows the previous filter's rows.

  Fix: keep the query that was submitted, and clear the rows on every reset before the fetch.
- **m12. The run check trusts the read index** (`relay.py:317`). It finds the start event and its `actor_ref` (which becomes `on_behalf_of`) in `ledger.event_index`, not in the verified log. Someone who can write the index can attribute a run to another person. Fix: fetch the start entry from the store by its seq and compare it, as the read routes do.
- **m13. `MemoryLedger.reanchor` uses `self._dbs[db]`** (`store.py:232`), so an unknown database gives a KeyError and a 500 rather than `UnknownDatabase` and a 404.
- **m14. Events and their index are read one at a time:** 100 `verifiedGet` round trips per page on immudb, and `/ledger/projects` logs into every project database on each call. That's fine at today's scale. Note it for phase 10.
- **m15. Test gap: the checker's head match.** Removing `head.seq == len(body) and head.chain == chain` (`verify-ledger-export.py:116`) survives every test. Every forgery test re-hashes the head's chain too, so the signature catches it first. The attack this line stops, edited entries with re-hashed proofs under the original signed head, isn't tested. Add that case.
- **m16. Test gap: the beacon's own witness check.** Removing the route's `if problem:` (`app.py:1814`) survives. The beacon tests run in `enforce`, where the middleware already refuses. The check exists for `record` mode, and no test covers it. Add a `record` mode beacon test with no request id and with someone else's (both 401).
- **m17. Test gap: `X-Forwarded-*` on the internal ledger route.** Removing that 404 survives the whole ledger suite (511 passed). Add the test that `/internal/resolve` has.
- **m18. Test gaps: the emitter and the 501.** Taking `emitter` from the body instead of the token survives the internal tests, because no test sends an `emitter` field. No test covers the export's 501 on immudb, so turning it into a 200 with an empty head would go unnoticed. Add both.

## What is sound

- **Isolation (I9).** `_ledger_project` uses `role_or_404`, so a stranger gets 404 and a lesser role is never upgraded. The SQL is fixed to `log = <this project's database>`, and `events/{seq}` reads only that database. The filter column names come from a fixed dict, and `LIMIT` is a constant. The export needs `EXPORT_ROLES` (owners) or admin, as `effective_role` gives.
- **Export keys.** The export carries `derive_all(pid, "content")` only. `before`/`after` use the `state` key, which is never exported. Fingerprint, query and mapping keys and the master keys never leave. The privacy test checks this, and the mutation that exports another scope's key is caught.
- **The memory-store export design.** The checker recomputes every link from genesis, requires `seq == line number` and `head.seq == len(body)`, and verifies an ECDSA P-256 signature over the canonical `{log, seq, chain}`. A swap, a dropped first or last entry, trailing lines, a mid-file head or a re-signed file all fail. `head.keys` is unsigned, but a substituted key can't make forged content pass a 128-bit HMAC under the signed digest, so that only denies service. Canonical JSON matches the platform's on 3000 random values. The design is sound for the memory store. On immudb, the 501 is the right answer until S9.
- **Internal route (I2, T17).** The caller comes from its own token, compared in constant time, and becomes the emitter. The relay binds actions to emitters. Actor-like fields anywhere in the body (top level via `extra`, or in details) are rejected as `actor_supplied`. `occurred_at` is the platform's receive time. The new project check in `_judge_run` rejects a run that cites another project's request. Reached through Caddy (`X-Forwarded-*`), the route is 404, and the launcher also blocks `/api/internal/*`.
- **Beacon.** Only `page.*` with `origin=browser` is accepted, with the registry's detail keys. The request must be witnessed and the presenter's own, including in `record` mode. A request id carries one beacon (unique index). Page views go to `ledger.page_view` only, never to immudb. The beacon's own POST is witnessed into the platform log like any write, which is what spec 3.5 asks for.
- **`logs.html`.** Text is set with `textContent` only. The slug is encoded wherever it is used. `[hidden]{display:none !important}` beats the button display. No stored data reaches HTML.

## Mutations (each applied to the scratchpad copy of 790bf57, then restored and diffed)

| Mutation | Tests run | Result |
|---|---|---|
| index columns not compared | routes: index alarm | caught |
| export role check removed | routes: export roles | caught |
| `_ledger_project` gives every caller 'owner' | routes: stranger 404 | caught |
| entry read without verification | routes: tampered entry | caught |
| checker signature check removed | routes + export_checker | caught |
| checker seq check removed | export_checker + routes | one error, no failure (the signature covers it) |
| checker head match removed | export_checker + routes | **survived** (m15) |
| export carries the platform scope's content key | privacy | caught |
| beacon detail keys unchecked | beacon | caught |
| beacon rate limit removed | beacon | caught |
| beacon role check removed | beacon | caught |
| beacon route's witness check removed | beacon | **survived** (m16) |
| `_judge_run` project check removed | internal: another project | caught |
| internal route `X-Forwarded-*` check removed | whole `tests/ledger` | **survived** (m17) |
| re-anchor open to any caller | routes | caught |
| re-anchor not recorded | routes | caught |
| memory re-anchor does nothing | routes + store | caught |
| emitter taken from the body | internal | **survived** (m18) |
| export 501 turned into 200 | none exists | no test (m18; my whole-suite run was interrupted, and grep finds no 501 test) |

After every mutation, `git show 790bf57:<file> | diff - <file>` was empty. The probe file and `mut.py` live only in my scratchpad. The repo checkout was never edited apart from this review file.
