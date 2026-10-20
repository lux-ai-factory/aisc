// Whose X-AISC-Request-Id the ledger cites.
//
// Caddy strips the header a client sends and puts back the one the platform's witness gave it, with
// the gateway token (X-Auth-Request-Access-Token) oauth2-proxy holds for the person. A caller that
// reaches the app directly on the backend network, with a token of its own or none, does not go
// through that, so the id it presents is not cited: only a request carrying a gateway token that
// verifies (the witness's own rule, aisc_identity.gateway) keeps its request id. With AUTH_ENABLED
// off (local work) nothing is verified, and the id is kept as presented.
import {
  generateKeyPairSync,
  sign as rsaSign,
  type KeyObject,
} from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ headers: new Headers() }));
vi.mock("next/headers", () => ({ headers: async () => state.headers }));

import { currentRequestId } from "@/vendor/aisc-ledger/emit";
import { keyForJwks, throughGateway } from "@/vendor/aisc-ledger/gatewayToken";

const ISSUER = "http://keycloak:8080/realms/aisc";
const JWKS = "http://keycloak:8080/realms/aisc/protocol/openid-connect/certs";
const REQUEST = "a6a6a6a6-0000-4000-8000-000000000002";

const pair = () => generateKeyPairSync("rsa", { modulusLength: 2048 });
const realm = pair();
const keyFor = async () => realm.publicKey;

function jwt(
  claims: Record<string, unknown>,
  key: KeyObject = realm.privateKey,
  kid = "realm-key",
): string {
  const part = (v: unknown) =>
    Buffer.from(JSON.stringify(v)).toString("base64url");
  const signed = `${part({ alg: "RS256", typ: "JWT", kid })}.${part(claims)}`;
  return `${signed}.${rsaSign("RSA-SHA256", Buffer.from(signed), key).toString("base64url")}`;
}

const token = (
  subject = "alice",
  azp = "aisc-gateway",
  extra: Record<string, unknown> = {},
) =>
  jwt({
    sub: subject,
    preferred_username: subject,
    iss: ISSUER,
    azp,
    exp: Math.floor(Date.now() / 1000) + 300,
    ...extra,
  });

const ENV = [
  "AUTH_ENABLED",
  "KEYCLOAK_ISSUER",
  "KEYCLOAK_JWKS_URL",
  "AISC_GATEWAY_CLIENT_ID",
] as const;
const saved: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const k of ENV) saved[k] = process.env[k];
  process.env.AUTH_ENABLED = "true";
  process.env.KEYCLOAK_ISSUER = ISSUER;
  process.env.KEYCLOAK_JWKS_URL = JWKS;
  delete process.env.AISC_GATEWAY_CLIENT_ID;
});

afterEach(() => {
  for (const k of ENV) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
  state.headers = new Headers();
  vi.unstubAllGlobals();
});

const through = (headers: Record<string, string>) =>
  throughGateway(new Headers(headers), { keyFor });

describe("a request id is kept only on a request that came through the gateway", () => {
  it("a request through the gateway cites its request", async () => {
    expect(
      await through({
        "x-aisc-request-id": REQUEST,
        "x-auth-request-access-token": token(),
      }),
    ).toBe(true);
  });

  it("a direct caller with its own token (not the gateway's) cites nothing", async () => {
    expect(
      await through({
        "x-aisc-request-id": REQUEST,
        authorization: `Bearer ${token("alice", "some-service")}`,
      }),
    ).toBe(false);
  });

  it("a direct caller with no token cites nothing", async () => {
    expect(await through({ "x-aisc-request-id": REQUEST })).toBe(false);
  });

  it("a token from another client in the gateway header cites nothing", async () => {
    expect(
      await through({
        "x-auth-request-access-token": token("alice", "other"),
      }),
    ).toBe(false);
  });

  it("a Bearer naming another person than the gateway token cites nothing", async () => {
    expect(
      await through({
        "x-auth-request-access-token": token("alice"),
        authorization: `Bearer ${token("mallory", "other")}`,
      }),
    ).toBe(false);
  });

  it("a Bearer for the same person from another client is fine (the engine's web app)", async () => {
    expect(
      await through({
        "x-auth-request-access-token": token("alice"),
        authorization: `Bearer ${token("alice", "aisc-webapp")}`,
      }),
    ).toBe(true);
  });

  it("a forged gateway token cites nothing", async () => {
    const forged = jwt(
      {
        sub: "alice",
        iss: ISSUER,
        azp: "aisc-gateway",
        exp: Math.floor(Date.now() / 1000) + 300,
      },
      pair().privateKey,
    );
    expect(await through({ "x-auth-request-access-token": forged })).toBe(
      false,
    );
  });

  it("an expired, foreign-issuer or unsigned gateway token cites nothing", async () => {
    const past = Math.floor(Date.now() / 1000) - 120;
    expect(
      await through({
        "x-auth-request-access-token": token("alice", "aisc-gateway", {
          exp: past,
        }),
      }),
    ).toBe(false);
    expect(
      await through({
        "x-auth-request-access-token": token("alice", "aisc-gateway", {
          iss: "http://elsewhere/realms/aisc",
        }),
      }),
    ).toBe(false);
    const part = (v: unknown) =>
      Buffer.from(JSON.stringify(v)).toString("base64url");
    const none = `${part({ alg: "none" })}.${part({ sub: "alice", iss: ISSUER, azp: "aisc-gateway", exp: past + 1000 })}.`;
    expect(await through({ "x-auth-request-access-token": none })).toBe(false);
  });

  it("the gateway client can be renamed (AISC_GATEWAY_CLIENT_ID)", async () => {
    process.env.AISC_GATEWAY_CLIENT_ID = "edge";
    expect(
      await through({ "x-auth-request-access-token": token("alice", "edge") }),
    ).toBe(true);
    expect(await through({ "x-auth-request-access-token": token() })).toBe(
      false,
    );
  });

  it("with AUTH_ENABLED off the presented id is kept", async () => {
    process.env.AUTH_ENABLED = "false";
    expect(await through({ "x-aisc-request-id": REQUEST })).toBe(true);
  });

  it("with auth on but nothing to verify with, nothing is cited", async () => {
    delete process.env.KEYCLOAK_ISSUER;
    delete process.env.KEYCLOAK_JWKS_URL;
    expect(await through({ "x-auth-request-access-token": token() })).toBe(
      false,
    );
  });
});

describe("currentRequestId, which every event and outgoing call reads", () => {
  const realmJwks = () => {
    const jwk = realm.publicKey.export({ format: "jwk" });
    return { keys: [{ ...jwk, kid: "realm-key", alg: "RS256", use: "sig" }] };
  };

  it("drops the id a direct caller presents (the attack)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(realmJwks()))),
    );
    state.headers = new Headers({
      "x-aisc-request-id": REQUEST,
      authorization: `Bearer ${token("alice", "some-service")}`,
    });
    expect(await currentRequestId()).toBeNull();
  });

  it("keeps the id of a request through the gateway, reading the realm's JWKS", async () => {
    const fetched = vi.fn(
      async (_url: string) => new Response(JSON.stringify(realmJwks())),
    );
    vi.stubGlobal("fetch", fetched);
    state.headers = new Headers({
      "x-aisc-request-id": REQUEST,
      "x-auth-request-access-token": token(),
    });
    expect(await currentRequestId()).toBe(REQUEST);
    expect(fetched.mock.calls.every(([url]) => url === JWKS)).toBe(true);
  });
});

describe("keyForJwks", () => {
  it("finds the key by kid and refuses a kid the realm does not have", async () => {
    const jwk = realm.publicKey.export({ format: "jwk" });
    const fetched = vi.fn(
      async () =>
        new Response(JSON.stringify({ keys: [{ ...jwk, kid: "k1" }] })),
    );
    const keys = keyForJwks(
      "http://realm-a/certs",
      fetched as unknown as typeof fetch,
    );
    const key = await keys({ kid: "k1", alg: "RS256" });
    expect(key.asymmetricKeyType).toBe("rsa");
    await expect(keys({ kid: "unknown", alg: "RS256" })).rejects.toThrow();
  });
});
