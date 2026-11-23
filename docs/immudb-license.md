# immudb license check

Checked **2026-11-16** against the actual image configured in
`docker-compose-infra.development.yml`: `codenotary/immudb:1.11.1`.

## Source

The [v1.11.1 LICENSE](https://github.com/codenotary/immudb/blob/v1.11.1/LICENSE)
is **Business Source License 1.1 (BSL)**, with a Codenotary additional use grant.
The [current upstream LICENSE](https://github.com/codenotary/immudb/blob/master/LICENSE)
has the same terms at the time of this check. License terms must be checked per version.

## What it permits

- Copying, modification and redistribution, subject to retaining the license notices.
- Production use, except offering immudb on a hosted or embedded basis in a **paid competitive offering**.
- Internal organisational use is expressly not competitive.
- Products not provided on a paid basis are expressly not competitive.

The license defines competition as a paid product (including paid support) that **significantly
overlaps with the capabilities of Codenotary's paid versions**. It covers both hosted services and
embedded distributions, including packaging that requires downloading immudb to operate.

## Implications for AISC

An open-source AISC application can use immudb, but this immudb release itself is **source-available,
not OSI-open-source**: it restricts commercial fields of use. AISC's code does not automatically
become BSL merely because it uses a separate immudb service; the dependency keeps its own license.

A paid AI-assessment SaaS is **not automatically prohibited**. Production use is permitted when the
offering does not meet the competitive-offering definition. This is conditional permission, not a
blanket guarantee for every downstream SaaS or paid supported distribution. An offering approaching
audit/database services should resolve that overlap with Codenotary (`info@codenotary.com`).

Each version changes to **Apache 2.0 four years after publication**, under the license's per-version
change terms. Do not assume that the current release is already Apache-licensed, or infer a change
date solely from a copyright year.

## Refactor decision

Keep main's existing immudb audit implementation for now, per
[ADR 0001](adr/0001-mainline-first-consolidation.md). No second audit store or commercial license
purchase is introduced by this documentation decision.
