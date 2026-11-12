# Architecture decision records (ADRs)

An ADR records a **decision that changes or waives an invariant** in [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).
Ordinary code changes do not need one; a change that moves a boundary, adds a service/database/datastore,
or breaks an invariant does.

- One file per decision: `NNNN-short-title.md` (next number, zero-padded).
- Copy [`0000-template.md`](0000-template.md).
- Once **accepted**, an ADR is not edited. To change it, write a new ADR and mark the old one
  `superseded by NNNN`.
- An ADR that waives an invariant names the **guard allowlist entry** it corresponds to and the condition
  under which the waiver is removed.
- Link the ADR from the PR: *"breaks I<n>; see ADR NNNN."*

The point is to make "someone ran ahead" into "the team decided", with a cost and an exit — cheaply.
