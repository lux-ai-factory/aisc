// The JWKS lookup behind the request id an event cites.
//
// - A Keycloak that accepts the connection but never answers must not hold a save: the read
//   gives up after JWKS_TIMEOUT_MS (2 seconds, or the timeoutMs given) and the token does not verify.
// - A failed read is throttled like a successful one (at most one read every 10 seconds).
import { generateKeyPairSync, sign as rsaSign } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ headers: new Headers() }));
vi.mock("next/headers", () => ({ headers: async () => state.headers }));

import { JWKS_TIMEOUT_MS, keyForJwks, verifyToken } from "@/vendor/aisc-ledger/gatewayToken";

const ISSUER = "http://keycloak:8080/realms/aisc";
const realm = generateKeyPairSync("rsa", { modulusLength: 2048 });

function jwt(claims: Record<string, unknown>): string {
  const part = (v: unknown) =>
    Buffer.from(JSON.stringify(v)).toString("base64url");
  const signed = `${part({ alg: "RS256", typ: "JWT", kid: "realm-key" })}.${part(claims)}`;
  return `${signed}.${rsaSign("RSA-SHA256", Buffer.from(signed), realm.privateKey).toString("base64url")}`;
}
const gatewayToken = () =>
  jwt({
    sub: "alice",
    iss: ISSUER,
    azp: "aisc-gateway",
    exp: Math.floor(Date.now() / 1000) + 300,
  });

const ENV = [
  "AUTH_ENABLED",
  "KEYCLOAK_ISSUER",
  "KEYCLOAK_JWKS_URL",
  "LEDGER_MODE",
] as const;
const saved: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const k of ENV) saved[k] = process.env[k];
  process.env.AUTH_ENABLED = "true";
  process.env.KEYCLOAK_ISSUER = ISSUER;
});

afterEach(() => {
  for (const k of ENV) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
  state.headers = new Headers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("keyForJwks", () => {
  it("gives up on a JWKS that never answers within JWKS_TIMEOUT_MS, so the token does not verify", async () => {
    vi.useFakeTimers();
    const never = vi.fn(() => new Promise<Response>(() => {}));
    const keyFor = keyForJwks(
      "http://slow-realm/certs",
      never as unknown as typeof fetch,
    );
    let result: unknown = "pending";
    const pending = verifyToken(gatewayToken(), {
      issuer: ISSUER,
      keyFor,
    }).then((r) => {
      result = r;
    });
    expect(JWKS_TIMEOUT_MS).toBe(2_000);
    await vi.advanceTimersByTimeAsync(JWKS_TIMEOUT_MS);
    expect(result).toBeNull();
    await pending;
    expect(never).toHaveBeenCalledTimes(1);
  });

  it("throttles a failed read too: two lookups 1 second apart make one fetch", async () => {
    vi.useFakeTimers();
    const down = vi.fn(async () => new Response("down", { status: 503 }));
    const keyFor = keyForJwks(
      "http://down-realm/certs",
      down as unknown as typeof fetch,
    );
    await expect(keyFor({ kid: "realm-key" })).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(keyFor({ kid: "realm-key" })).rejects.toThrow();
    expect(down).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    await expect(keyFor({ kid: "realm-key" })).rejects.toThrow();
    expect(down).toHaveBeenCalledTimes(2);
  });

  it("takes a shorter timeout when one is given", async () => {
    vi.useFakeTimers();
    const never = vi.fn(() => new Promise<Response>(() => {}));
    const keyFor = keyForJwks("http://slow-realm/certs", never as unknown as typeof fetch, { timeoutMs: 50 });
    let result: unknown = "pending";
    const pending = verifyToken(gatewayToken(), { issuer: ISSUER, keyFor }).then((r) => {
      result = r;
    });
    await vi.advanceTimersByTimeAsync(50);
    expect(result).toBeNull();
    await pending;
  });
});
