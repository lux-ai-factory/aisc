// AUTH_ENABLED and LEDGER_MODE are read strictly, the same way as aisc_identity.switches in Python: on the
// shared cases (shared/identity/switch-cases.json, copied unchanged to test/fixtures/switch-cases.json).
// Anything that is not an on or off word, or one of the three ledger modes, is refused, empty included.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

type Case = { value: string | null; is?: boolean | string; refused?: boolean };
const CASES = JSON.parse(
  readFileSync(new URL("../../fixtures/switch-cases.json", import.meta.url), "utf8"),
) as { switch: Case[]; auth_enabled: Case[]; ledger_mode: Case[] };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function parser(): Promise<any> {
  const path = "@/vendor/aisc-ledger/switches";
  try {
    return await import(/* @vite-ignore */ path);
  } catch (e) {
    expect.fail(`there is no strict switch parser (src/vendor/aisc-ledger/switches.ts): ${String(e)}`);
  }
}

const envOf = (name: string, c: Case) => (c.value === null ? {} : { [name]: c.value });

describe("strict switches", () => {
  it.each(CASES.switch.map((c) => [JSON.stringify(c.value), c] as const))("switch %s", async (_n, c) => {
    const s = await parser();
    if (c.refused) expect(() => s.parseSwitch("AUTH_ENABLED", c.value)).toThrow(s.SwitchInvalid);
    else expect(s.parseSwitch("AUTH_ENABLED", c.value)).toBe(c.is);
  });

  it.each(CASES.auth_enabled.map((c) => [JSON.stringify(c.value), c] as const))("auth enabled %s", async (_n, c) => {
    const s = await parser();
    const env = envOf("AUTH_ENABLED", c);
    if (c.refused) expect(() => s.authEnabled(env)).toThrow(s.SwitchInvalid);
    else expect(s.authEnabled(env)).toBe(c.is);
  });

  it.each(CASES.ledger_mode.map((c) => [JSON.stringify(c.value), c] as const))("ledger mode %s", async (_n, c) => {
    const s = await parser();
    const env = envOf("LEDGER_MODE", c);
    if (c.refused) expect(() => s.ledgerMode(env)).toThrow(s.SwitchInvalid);
    else expect(s.ledgerMode(env)).toBe(c.is);
  });

  it("checks both switches at once, absent meaning on and record", async () => {
    const s = await parser();
    expect(s.checkSwitches({})).toEqual({ AUTH_ENABLED: true, LEDGER_MODE: "record" });
  });
});
