// Run from each Next.js app, where this file is vendored as test/vendor/cardChange.test.ts next to
// src/vendor/aisc-access/cardChange.ts.
import { describe, expect, it, vi } from "vitest";
import { cardChange, cardChangedSince } from "@/vendor/aisc-access/cardChange";

// A page drawn on one card state shows "The AI card changed since you started (who, when)" when it is no longer
// the latest (docs/specs/who-does-what.md, section 3). The latest is the project database's work.card_change().

const V1 = "11111111-1111-4111-8111-111111111111";
const V2 = "22222222-2222-4222-8222-222222222222";
const now = (version: string, revision: number, by: string | null = "Maria Rossi") =>
  ({ version, number: version === V1 ? 1 : 2, revision, by, at: "2026-01-20T11:02:00+00:00" });

describe("the card changed since the page was drawn", () => {
  it("says nothing while the page's card state is the latest", () => {
    expect(cardChangedSince({ version: V1, revision: 2 }, now(V1, 2))).toBeNull();
  });

  it("names who stored the newer card state and when, after a correction or a new version", () => {
    const said = "The AI card changed since you started (Maria Rossi, 11:02 UTC).";
    expect(cardChangedSince({ version: V1, revision: 1 }, now(V1, 2))).toBe(said);
    expect(cardChangedSince({ version: V1, revision: 2 }, now(V2, 1))).toBe(said);
  });

  it("gives the time alone when nobody is recorded", () => {
    expect(cardChangedSince({ version: V1, revision: 1 }, now(V1, 2, null)))
      .toBe("The AI card changed since you started (11:02 UTC).");
  });

  it("a page drawn before the project had a card says so once one is stored", () => {
    expect(cardChangedSince(null, now(V1, 1))).toBe("The AI card changed since you started (Maria Rossi, 11:02 UTC).");
    expect(cardChangedSince(null, null)).toBeNull();
  });

  it("reads the latest card state from the project database", async () => {
    const tx = { $queryRaw: vi.fn(async (..._sql: unknown[]) => [{ change: now(V1, 2) }]) };
    expect(await cardChange(tx)).toEqual(now(V1, 2));
    expect((tx.$queryRaw.mock.calls[0][0] as TemplateStringsArray).join("?")).toContain("work.card_change()");
  });
});
