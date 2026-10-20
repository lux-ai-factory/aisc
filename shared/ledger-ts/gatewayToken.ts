/**
 * Did this request come through the gateway: the witness's rule
 * (aisc_identity.gateway), for the request id the ledger cites.
 *
 * Caddy strips the X-AISC-Request-Id a client sends and puts back the one the
 * platform's witness gave it, with the gateway token
 * (X-Auth-Request-Access-Token) oauth2-proxy holds for the person. A caller
 * reaching this app directly on the backend network, with no token or one of
 * its own, could otherwise make an event cite any request it names. So the id
 * is kept only when:
 *
 * - the gateway token verifies against the realm (RS256, issuer, expiry) and
 *   was issued to the gateway's own client (`azp`, AISC_GATEWAY_CLIENT_ID,
 *   default "aisc-gateway");
 * - a Bearer token on the same request, if any, verifies too and names the
 *   same person (`sub`); its client is not checked.
 *
 * With AUTH_ENABLED off (local work) nothing is verified anywhere, and the
 * presented id is kept.
 *
 * Vendored into each Next.js app as src/vendor/aisc-ledger/gatewayToken.ts
 * (shared/ledger-ts/README.md). With it on (the default) but no KEYCLOAK_ISSUER or
 * KEYCLOAK_JWKS_URL to verify with, nothing is kept.
 */
import {
  createPublicKey,
  verify as rsaVerify,
  type JsonWebKey,
  type KeyObject,
} from "node:crypto";

export const GATEWAY_TOKEN_HEADER = "x-auth-request-access-token";

type Claims = Record<string, unknown>;
type JoseHeader = { alg?: string; kid?: string };

/** The key that signed a token, by its header. Rejects when there is none. */
export type KeyFor = (header: JoseHeader) => Promise<KeyObject>;

/** Seconds a token may be past its expiry while the request crosses the gateway. */
const LEEWAY = 30;

const segment = (text: string): unknown =>
  JSON.parse(Buffer.from(text, "base64url").toString("utf8"));

const isObject = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);

/** The claims of a token that verifies, or null. Never throws. */
export async function verifyToken(
  token: string,
  { issuer, keyFor }: { issuer: string; keyFor: KeyFor },
): Promise<Claims | null> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts.some((p) => !/^[A-Za-z0-9_-]+$/.test(p)))
    return null;
  try {
    const header = segment(parts[0]);
    const claims = segment(parts[1]);
    if (!isObject(header) || !isObject(claims)) return null;
    if (header.alg !== "RS256") return null;
    const key = await keyFor(header as JoseHeader);
    const signed = Buffer.from(`${parts[0]}.${parts[1]}`);
    if (
      !rsaVerify("RSA-SHA256", signed, key, Buffer.from(parts[2], "base64url"))
    )
      return null;
    const now = Date.now() / 1000;
    if (claims.iss !== issuer) return null;
    if (typeof claims.sub !== "string" || claims.sub === "") return null;
    if (typeof claims.exp !== "number" || claims.exp + LEEWAY < now)
      return null;
    if (typeof claims.nbf === "number" && claims.nbf - LEEWAY > now)
      return null;
    return claims;
  } catch {
    return null; // unreadable segment, no key for it
  }
}

const jwksClients = new Map<string, KeyFor>();

/**
 * How long a JWKS read may take by default. An app that resolves the request id inside a write's
 * transaction must stay well under Prisma's 5-second interactive timeout.
 */
export const JWKS_TIMEOUT_MS = 2_000;
/** A kid the keys do not have is looked up again at most this often, after a success or a failure. */
const JWKS_REREAD_MS = 10_000;

/** `fetchImpl(url)`, given up after `ms` even if the fetch ignores its abort signal. */
async function fetchWithin(
  fetchImpl: typeof fetch,
  url: string,
  ms: number,
): Promise<Response> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timedOut = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error(`JWKS did not answer within ${ms} ms`));
    }, ms);
  });
  try {
    return await Promise.race([
      fetchImpl(url, { cache: "no-store", signal: controller.signal }),
      timedOut,
    ]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * A key lookup reading the realm's JWKS, cached; read again when a kid is new, at most every
 * 10 seconds whether the last read worked or not (a JWKS that cannot be read is not asked on
 * every call), and never for longer than `timeoutMs`. Lookups during a read share it.
 */
export function keyForJwks(
  jwksUrl: string,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
  { timeoutMs = JWKS_TIMEOUT_MS }: { timeoutMs?: number } = {},
): KeyFor {
  let keys = new Map<string, KeyObject>();
  let loaded = 0;
  let loading: Promise<void> | null = null;
  const read = async () => {
    const response = await fetchWithin(fetchImpl, jwksUrl, timeoutMs);
    if (!response.ok) throw new Error(`JWKS answered ${response.status}`);
    const body = (await response.json()) as { keys?: JsonWebKey[] };
    const next = new Map<string, KeyObject>();
    for (const jwk of body.keys ?? []) {
      if (jwk.kty !== "RSA" || typeof jwk.kid !== "string") continue;
      if (jwk.use !== undefined && jwk.use !== "sig") continue;
      next.set(jwk.kid, createPublicKey({ key: jwk, format: "jwk" }));
    }
    keys = next;
  };
  const load = () => {
    loading ??= read().finally(() => {
      loaded = Date.now();
      loading = null;
    });
    return loading;
  };
  return async ({ kid }) => {
    if (typeof kid !== "string") throw new Error("the token names no key");
    // A new kid is looked up again (a key rotation), at most every 10 seconds.
    if (!keys.has(kid) && (loading || Date.now() - loaded > JWKS_REREAD_MS))
      await load();
    const key = keys.get(kid);
    if (!key) throw new Error("the realm has no such key");
    return key;
  };
}

function cachedKeyFor(jwksUrl: string): KeyFor {
  let client = jwksClients.get(jwksUrl);
  if (!client) {
    client = keyForJwks(jwksUrl);
    jwksClients.set(jwksUrl, client);
  }
  return client;
}

/** On unless set to something else than 1/true/yes/on, as aisc_identity reads it. */
const authEnabled = () =>
  ["1", "true", "yes", "on"].includes(
    (process.env.AUTH_ENABLED ?? "true").trim().toLowerCase(),
  );

/** Whether this request came through the gateway (see the top of the file). */
export async function throughGateway(
  headers: { get(name: string): string | null },
  deps: { keyFor?: KeyFor } = {},
): Promise<boolean> {
  if (!authEnabled()) return true;
  const issuer = process.env.KEYCLOAK_ISSUER ?? "";
  const jwksUrl = process.env.KEYCLOAK_JWKS_URL ?? "";
  if (!issuer || !jwksUrl) return false;
  const keyFor = deps.keyFor ?? cachedKeyFor(jwksUrl);
  const gatewayToken = (headers.get(GATEWAY_TOKEN_HEADER) ?? "").trim();
  if (!gatewayToken) return false;
  const claims = await verifyToken(gatewayToken, { issuer, keyFor });
  if (!claims) return false;
  const gatewayClient = process.env.AISC_GATEWAY_CLIENT_ID || "aisc-gateway";
  if (claims.azp !== gatewayClient) return false;
  const authorization = (headers.get("authorization") ?? "").trim();
  if (authorization) {
    const bearer = authorization.toLowerCase().startsWith("bearer ")
      ? authorization.slice(7).trim()
      : "";
    const other = bearer ? await verifyToken(bearer, { issuer, keyFor }) : null;
    if (!other || other.sub !== claims.sub) return false;
  }
  return true;
}
