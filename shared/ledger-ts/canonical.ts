/**
 * RFC 8785 JSON canonicalisation, the TypeScript twin of the platform's
 * platform_service/ledger/canonical.py: the same rules, checked against the
 * same vectors (test/fixtures/ledger/canonical_vectors.json, made by the
 * platform's own code).
 *
 * `canonical` is exact RFC 8785 (the platform's bytes for the shared vectors).
 * `ledgerSafe` is what the emitter checks before writing: canonical JSON, and
 * no integer-valued number beyond 2**53, which jsonb keeps as an integer the
 * relay refuses. Such an event would only be rejected later, so the write fails
 * now, in the person's own transaction, where they see it.
 */

const MAX_SAFE = 2 ** 53;

export class NotCanonical extends Error {}

export function canonical(value: unknown): string {
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") return number(value);
  if (typeof value === "bigint") {
    if (value > BigInt(MAX_SAFE) || value < -BigInt(MAX_SAFE))
      throw new NotCanonical(`integer beyond 2**53: ${value}`);
    return value.toString();
  }
  if (typeof value === "string") return text(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (typeof value === "object") {
    const keys = Object.keys(value as object).sort(); // default sort: UTF-16 code units, as RFC 8785 asks
    return (
      "{" +
      keys
        .map(
          (k) =>
            text(k) + ":" + canonical((value as Record<string, unknown>)[k]),
        )
        .join(",") +
      "}"
    );
  }
  throw new NotCanonical(`JSON has no form for ${typeof value}`);
}

function number(x: number): string {
  if (!Number.isFinite(x))
    throw new NotCanonical("NaN and infinities have no JSON form");
  return Object.is(x, -0) ? "0" : String(x); // ECMAScript Number::toString is RFC 8785's form
}

/** Throws NotCanonical unless the ledger can keep `value` as it is (see the file's comment). */
export function ledgerSafe(value: unknown): void {
  canonical(value);
  const walk = (v: unknown): void => {
    if (
      typeof v === "number" &&
      Number.isInteger(v) &&
      Math.abs(v) > MAX_SAFE
    ) {
      throw new NotCanonical(
        `integer beyond 2**53: ${v} (jsonb keeps it as an integer the ledger refuses)`,
      );
    }
    // jsonb has no form for U+0000 (Postgres refuses "\u0000"), so the event's insert would fail.
    if (typeof v === "string" && v.includes("\u0000"))
      throw new NotCanonical(
        "a NUL character (U+0000), which jsonb cannot keep",
      );
    if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") {
      for (const [k, item] of Object.entries(v)) {
        walk(k);
        walk(item);
      }
    }
  };
  walk(value);
}

function text(s: string): string {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = s.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        i++;
        continue;
      }
      throw new NotCanonical("a lone surrogate has no UTF-8 form");
    }
    if (c >= 0xdc00 && c <= 0xdfff)
      throw new NotCanonical("a lone surrogate has no UTF-8 form");
  }
  return JSON.stringify(s); // escapes " \ and controls as RFC 8785 does (\b \f \n \r \t, else \u00xx)
}
