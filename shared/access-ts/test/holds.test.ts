// Run from each Next.js app, where this file is vendored as test/vendor/holds.test.ts next to
// src/vendor/aisc-access/holds.ts and the shared cases as test/fixtures/hold-refusal-cases.json
// (shared/identity, also run by aisc_identity.holds).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { claimForSave, HoldRefused, NotInTransaction, refusalFor } from "@/vendor/aisc-access/holds";
import { isRefusal } from "@/vendor/aisc-access/refusal";

type Case = {
  name: string;
  sqlstate: string;
  detail: Record<string, unknown> | null;
  label: string;
  person: string;
  now: string;
  refusal: unknown;
};
const CASES = (
  JSON.parse(readFileSync(new URL("../fixtures/hold-refusal-cases.json", import.meta.url), "utf8")) as {
    cases: Case[];
  }
).cases;

/** What Prisma throws for an error a raw query raised: the SQLSTATE in meta.code, the DETAIL in meta.message. */
function prismaError(sqlstate: string, detail: string | null) {
  return Object.assign(new Error("Raw query failed."), {
    code: "P2010",
    meta: { code: sqlstate, message: `ERROR: refused${detail === null ? "" : `\nDETAIL: ${detail}`}` },
  });
}

const failing = (error: unknown) => ({ $executeRaw: async () => Promise.reject(error) });
const WHERE = ["fill_checklist", "submission-1", "governance", "Governance", "luca-subject", "Luca Bianchi"] as const;

describe("a refused save", () => {
  it.each(CASES.map((c) => [c.name, c] as const))("answers the refusal of its case: %s", (_n, c) => {
    const refusal = refusalFor(c.sqlstate, c.detail === null ? null : JSON.stringify(c.detail), {
      label: c.label,
      personName: c.person,
      now: new Date(c.now),
    });
    expect(refusal).toEqual(c.refusal);
    expect(isRefusal(refusal)).toBe(true);
  });

  it("is no refusal for another database error", () => {
    expect(refusalFor("23505", null, { label: "Governance", personName: "Luca Bianchi" })).toBeNull();
  });

  it("throws the refusal when someone else holds the part", async () => {
    const detail = JSON.stringify({ holder: "Maria Rossi", since: "2026-01-20T10:40:12+00:00" });
    const thrown = await claimForSave(failing(prismaError("AH001", detail)), ...WHERE).catch((e) => e);
    expect(thrown).toBeInstanceOf(HoldRefused);
    expect((thrown as HoldRefused).refusal.code).toBe("not_holder");
    expect((thrown as HoldRefused).refusal.current.changed_by).toBe("Maria Rossi");
  });

  it("passes another error on as it came", async () => {
    const other = prismaError("23505", null);
    await expect(claimForSave(failing(other), ...WHERE)).rejects.toBe(other);
  });

  it("is claimed only inside a transaction", async () => {
    const client = { $executeRaw: async () => 1, $transaction: async () => undefined };
    await expect(claimForSave(client, ...WHERE)).rejects.toBeInstanceOf(NotInTransaction);
  });
});
