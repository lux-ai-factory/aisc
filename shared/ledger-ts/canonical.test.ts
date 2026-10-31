// The TypeScript canonical twin agrees with the platform's, byte for byte: on the shared vectors
// (platform/tests/ledger/fixtures/canonical_vectors.json) and on 1,500 random values
// (canonical_vectors_random.json), both made by the platform's code and copied here unchanged.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { canonical, ledgerSafe, NotCanonical } from "@/vendor/aisc-ledger/canonical";

const read = (name: string) =>
  JSON.parse(
    readFileSync(
      new URL(`../../fixtures/ledger/${name}`, import.meta.url),
      "utf8",
    ),
  );
const shared = read("canonical_vectors.json") as {
  vectors: { name: string; input_json: string; canonical: string }[];
};
const random = read("canonical_vectors_random.json") as {
  vectors: { json: string; canonical: string }[];
  not_ledger_safe: string[];
};

describe("canonical", () => {
  it.each(shared.vectors.map((v) => [v.name, v] as const))(
    "gives the platform's bytes: %s",
    (_name, v) => {
      expect(canonical(JSON.parse(v.input_json))).toBe(v.canonical);
    },
  );

  it("gives the platform's bytes for 1,500 random values", () => {
    expect(random.vectors.length).toBe(1500);
    for (const v of random.vectors)
      expect(canonical(JSON.parse(v.json))).toBe(v.canonical);
  });

  it("refuses what JSON has no form for", () => {
    expect(() => canonical(undefined)).toThrow(NotCanonical);
    expect(() => canonical(NaN)).toThrow(NotCanonical);
    expect(() => canonical(() => 1)).toThrow(NotCanonical);
    expect(() => canonical("\ud800")).toThrow(NotCanonical);
  });
});

describe("ledgerSafe", () => {
  it.each(random.not_ledger_safe)(
    "refuses what the ledger would reject: %s",
    (text) => {
      expect(() => ledgerSafe(JSON.parse(text))).toThrow(NotCanonical);
    },
  );

  it("accepts the shared vectors' everyday values", () => {
    expect(() =>
      ledgerSafe({ a: 1, b: [0.1, -2, "x"], c: null }),
    ).not.toThrow();
  });
});

// A jsonb value cannot hold U+0000, so an event holding one would be refused only at
// the insert. ledgerSafe refuses it first, which also covers the card save's pre-check.
describe("ledgerSafe and U+0000", () => {
  it("refuses a NUL character in a string or a key", () => {
    expect(() => ledgerSafe({ a: "x\u0000y" })).toThrow(NotCanonical);
    expect(() => ledgerSafe({ ["k\u0000"]: 1 })).toThrow(NotCanonical);
  });
});

// What the ledger refuses, from the vectors aisc_identity.ledger_events and the platform also read
// (platform/tests/ledger/fixtures/canonical_refusals.json, copied unchanged).
const refusals = read("canonical_refusals.json") as {
  not_ledger_safe: { name: string; json: string }[];
  values: string[];
};

function cycleArray(): unknown[] {
  const items: unknown[] = [];
  items.push(items);
  return items;
}

function cycleObject(): Record<string, unknown> {
  const record: Record<string, unknown> = {};
  record.self = record;
  return record;
}

/** Each name in the vectors' `values`, built in TypeScript. Object keys are always text here. */
export const VALUES: Record<string, unknown[]> = {
  not_finite: [NaN, Infinity, -Infinity],
  key_not_text: [],
  date: [new Date("2026-01-01T00:00:00Z")],
  bigint: [BigInt(1), BigInt(2) ** BigInt(60)],
  cycle: [cycleArray(), cycleObject()],
};
const named = Object.entries(VALUES).flatMap(([name, values]) =>
  values.map((value, i) => [`${name} ${i}`, value] as const),
);

describe("the shared refusal vectors", () => {
  it("names only values built here", () => {
    expect(Object.keys(VALUES).sort()).toEqual([...refusals.values].sort());
  });

  it.each(refusals.not_ledger_safe.map((v) => [v.name, v.json] as const))(
    "ledgerSafe refuses %s",
    (_name, text) => {
      expect(() => ledgerSafe(JSON.parse(text))).toThrow(NotCanonical);
    },
  );

  it.each(named)("canonical and ledgerSafe refuse %s", (_name, value) => {
    expect(() => canonical({ v: value })).toThrow(NotCanonical);
    expect(() => ledgerSafe({ v: value })).toThrow(NotCanonical);
  });

  it("does not take a value seen twice for a cycle", () => {
    const shared = { a: 1 };
    expect(canonical({ one: shared, two: [shared, shared] })).toBe(
      '{"one":{"a":1},"two":[{"a":1},{"a":1}]}',
    );
  });
});
