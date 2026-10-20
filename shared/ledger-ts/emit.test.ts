// What the emitter writes, and that it writes nothing while the ledger is off.
// The database half is test/db/ledger.db.test.ts.
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotCanonical } from "@/vendor/aisc-ledger/canonical";
import { emitEvent, eventBody } from "@/vendor/aisc-ledger/emit";

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
