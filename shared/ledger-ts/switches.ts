/**
 * AUTH_ENABLED and LEDGER_MODE, read strictly: the twin of aisc_identity.switches in Python.
 *
 * A switch is on only for an on word and off only for an off word; a ledger mode is one of three words. Case
 * and surrounding spaces do not matter. Anything else, an empty value included, is refused with an error that
 * names the variable, so a typo stops the app instead of quietly turning authentication or the ledger off.
 * Absent AUTH_ENABLED means on; absent LEDGER_MODE means record. Both parsers pass the same cases
 * (shared/identity/switch-cases.json).
 */

export const ON_WORDS = ["1", "true", "yes", "on"] as const;
export const OFF_WORDS = ["0", "false", "no", "off"] as const;
export const LEDGER_MODES = ["off", "record", "enforce"] as const;

export type LedgerMode = (typeof LEDGER_MODES)[number];
type Env = Record<string, string | undefined>;

const SHOWN_VALUE_LENGTH = 40;

/** A switch holds a value that is none of its allowed words. */
export class SwitchInvalid extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SwitchInvalid";
  }
}

function refuse(name: string, value: string, allowed: readonly string[]): SwitchInvalid {
  const shown = JSON.stringify(value).slice(0, SHOWN_VALUE_LENGTH);
  return new SwitchInvalid(`${name}=${shown} is not allowed: use one of ${allowed.join(", ")}`);
}

export function parseSwitch(name: string, value: string): boolean {
  const word = value.trim().toLowerCase();
  if ((ON_WORDS as readonly string[]).includes(word)) return true;
  if ((OFF_WORDS as readonly string[]).includes(word)) return false;
  throw refuse(name, value, [...ON_WORDS, ...OFF_WORDS]);
}

export function authEnabled(env: Env = process.env): boolean {
  const value = env.AUTH_ENABLED;
  return value === undefined ? true : parseSwitch("AUTH_ENABLED", value);
}

export function ledgerMode(env: Env = process.env): LedgerMode {
  const value = env.LEDGER_MODE;
  if (value === undefined) return "record";
  const word = value.trim().toLowerCase();
  if ((LEDGER_MODES as readonly string[]).includes(word)) return word as LedgerMode;
  throw refuse("LEDGER_MODE", value, LEDGER_MODES);
}

/** Both switches as they will be read, or SwitchInvalid naming the first bad one. */
export function checkSwitches(env: Env = process.env): { AUTH_ENABLED: boolean; LEDGER_MODE: LedgerMode } {
  return { AUTH_ENABLED: authEnabled(env), LEDGER_MODE: ledgerMode(env) };
}
