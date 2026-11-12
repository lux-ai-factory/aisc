# Versioning

> From `SCRATCH-platform-adapters-discussion.md` §3. Itemised as smell #10 in
> [`03-code-smells.md`](03-code-smells.md).

---

## §3. Versioning — yes, but where and when?

**My position.** I agree there should be versioning. I do **not** agree with *where and when* pilot implements it.

**What pilot does (evidence).**
- A version is a row of `project.system`, in the per-project DB; created only by the platform `POST /projects/{p}/system-versions`, `number = max+1` under `pg_advisory_xact_lock` (`platform/platform_service/db.py:330-351`).
- Immutability is enforced by DB **triggers** (`system_only_latest_changes`, `platform/project-template/0006_project_system.sql:27-42`), not by app code.
- Each step **stamps independently** by reading "latest" in a *separate* transaction (controls `fill/actions.ts`; backend `signals/system_stamp.py:19-21`).
- History is messy: migration `0002` built `core.ai_system`/`ai_system_version` with `frozen_at`, then `0003` **reversed** it back to numbered `core.system` (`platform/migrations/0002…sql:23-44`, `0003…sql:39-76`).

**Challenges.**
- **Stamping race:** "latest when made" is read in a different transaction from version creation → concurrent saves can stamp `n` while the card becomes `n+1`.
- **Immutability hole:** triggers only forbid editing `number < max(number)`; **nothing blocks `DELETE`** of `project.system`, so deleting the newest rows makes an older "immutable" version editable again.
- **Inconsistent delete semantics:** evidence links `ON DELETE CASCADE` but checklist answers `ON DELETE NO ACTION` (`0019…sql` vs `20260926000000…sql`).
- **Cross-step skew:** report/evidence are version-selected, but checklist tiles always show latest answers → a "v2 report" can contain non-v2 inputs.

**Where I'd rather it live.** Linked to the AI system/component model in the Django backend (§4), as versioned ORM models with app-enforced invariants — one place, testable, not trigger-plus-five-apps. Decide when a version is cut (on explicit "publish" rather than every save?).

**Decision to force:** who cuts a version and when; where immutability is enforced.
