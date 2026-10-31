// What the emitter writes, and that it writes nothing while the ledger is off.
// The database half is test/db/ledger.db.test.ts.
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotCanonical } from "@/vendor/aisc-ledger/canonical";
import { emitEvent, eventBody, withoutAuthors } from "@/vendor/aisc-ledger/emit";

function recorder() {
  const calls: { sql: string; values: unknown[] }[] = [];
  return {
    calls,
    $executeRaw: async (query: TemplateStringsArray, ...values: unknown[]) => {
      calls.push({ sql: query.join("?"), values });
      return 1;
    },
  };
}

afterEach(() => vi.unstubAllEnvs());

describe("emitEvent", () => {
  it("writes nothing while LEDGER_MODE is off or unset", async () => {
    const tx = recorder();
    vi.stubEnv("LEDGER_MODE", "off");
    expect(
      await emitEvent(tx, {
        action: "qualification.created",
        itemType: "qualification",
        itemId: "q1",
      }),
    ).toBeNull();
    expect(tx.calls).toEqual([]);
  });

  it("calls ledger.emit with the event as jsonb, citing the request", async () => {
    const tx = recorder();
    vi.stubEnv("LEDGER_MODE", "record");
    const id = await emitEvent(tx, {
      action: "card.node_corrected",
      itemType: "qualification",
      itemId: "q1",
      details: { node: "n1" },
      content: { label: "x" },
      requestId: "11111111-1111-4111-8111-111111111111",
    });
    expect(tx.calls).toHaveLength(1);
    expect(tx.calls[0].sql).toBe("SELECT ledger.emit(?::jsonb)");
    const sent = JSON.parse(tx.calls[0].values[0] as string);
    expect(sent).toMatchObject({
      event_id: id,
      request_id: "11111111-1111-4111-8111-111111111111",
      action: "card.node_corrected",
      item_type: "qualification",
      item_id: "q1",
      details: { node: "n1" },
      content: { label: "x" },
    });
    expect(Object.keys(sent)).not.toContain("actor_ref"); // the app never names who acted
  });

  it("refuses, in the person's transaction, a value the ledger can't keep", () => {
    expect(() =>
      eventBody(
        { action: "a", itemType: "t", itemId: "1", content: { n: 2 ** 60 } },
        null,
      ),
    ).toThrow(NotCanonical);
  });
});

describe("eventBody and the shared refusal vectors", () => {
  const read = (name: string) =>
    JSON.parse(
      readFileSync(new URL(`../../fixtures/ledger/${name}`, import.meta.url), "utf8"),
    );
  const refusals = read("canonical_refusals.json") as {
    not_ledger_safe: { name: string; json: string }[];
  };
  const base = { action: "a", itemType: "t", itemId: "1" };

  it.each(refusals.not_ledger_safe.map((v) => [v.name, v.json] as const))(
    "refuses %s wherever the event holds it",
    (_name, text) => {
      for (const field of ["content", "before", "after", "details"])
        expect(() => eventBody({ ...base, [field]: { v: JSON.parse(text) } }, null)).toThrow(NotCanonical);
    },
  );

  it("refuses, rather than converts, a date, a BigInt or a value that contains itself", () => {
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    for (const value of [new Date("2026-01-01T00:00:00Z"), BigInt(1), cycle, NaN])
      for (const field of ["content", "details"])
        expect(() => eventBody({ ...base, [field]: { v: value } }, null)).toThrow(NotCanonical);
  });

  it("drops author fields from details too", () => {
    const sent = JSON.parse(
      eventBody({ ...base, details: { createdBy: "ada@x", savedBy: "ada@x", n: 1 } }, null),
    );
    expect(sent.details).toEqual({ n: 1 });
  });

  it("leaves what is not a plain object or array to the refusal, not to an empty object", () => {
    const at = new Date("2026-01-01T00:00:00Z");
    expect(withoutAuthors({ at })).toEqual({ at });
  });
});
