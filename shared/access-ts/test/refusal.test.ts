// Run from each Next.js app, where this file is vendored as test/vendor/refusal.test.ts next to
// src/vendor/aisc-access/refusal.ts and the shared cases as test/fixtures/refusal-cases.json
// (shared/identity, also run by aisc_identity.refusal).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { isRefusal } from "@/vendor/aisc-access/refusal";

type Cases = {
  codes: { code: string; http: number }[];
  valid: { name: string; refusal: unknown }[];
  invalid: { name: string; rule: string; refusal: unknown }[];
};
const CASES = JSON.parse(
  readFileSync(new URL("../fixtures/refusal-cases.json", import.meta.url), "utf8"),
) as Cases;
const EXAMPLE = CASES.valid[0].refusal as Record<string, unknown>;

describe("a refusal", () => {
  it.each(CASES.valid.map((c) => [c.name, c] as const))("is known as one: %s", (_n, c) => {
    expect(isRefusal(c.refusal)).toBe(true);
  });

  it.each(CASES.codes.map((c) => [c.code] as const))("may carry the code %s", (code) => {
    expect(isRefusal({ ...EXAMPLE, code })).toBe(true);
  });

  it.each(CASES.invalid.map((c) => [c.name, c] as const))("is not: %s", (_n, c) => {
    expect(isRefusal(c.refusal)).toBe(false);
  });

  it.each([
    ["nothing", null],
    ["a message alone", "Your changes were not saved."],
    ["a status", 409],
    ["an app's other error", { detail: "name: lower-case letters, digits and hyphens, up to 63" }],
  ] as const)("is not %s", (_n, value) => {
    expect(isRefusal(value)).toBe(false);
  });
});
