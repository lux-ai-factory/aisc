/**
 * May this caller do this in a project: the platform's answer, read.
 *
 * The rule lives once, in aisc_identity.access, and the platform serves it at
 * GET /authz/projects/{ref}?want={method}. This client asks and passes the
 * verdict on; it decides nothing, so the Next.js apps cannot drift from the
 * Python services. A platform that is not configured, not reachable, slow or
 * answering something unexpected is a 503: nobody gets in on a guess.
 *
 * Vendored into each Next.js app as src/vendor/aisc-access/projectAccess.ts;
 * a test in each app fails when its copy differs from this one.
 */

export type Admission =
  | { ok: true; pid: string; slug: string; role: string; admin: boolean; mayWrite: boolean }
  | { ok: false; status: 403 | 404 | 503; message: string };

export const UNAVAILABLE = "Who may be here cannot be established just now.";

const PROJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const REFUSALS = new Set([403, 404, 503]);

export function isProjectId(ref: string): boolean {
  return PROJECT_ID.test(ref);
}

/** The project a path is inside, or null. A malformed escape comes back as it is, for the pid check to refuse. */
export function projectFromPath(pathname: string): string | null {
  const match = /^\/p\/([^/]+)/.exec(pathname);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

type Options = { platformUrl: string; fetchImpl?: typeof fetch; timeoutMs?: number };

export async function admit(
  project: string,
  method: string,
  token: string | null,
  { platformUrl, fetchImpl = fetch, timeoutMs = 3000 }: Options,
): Promise<Admission> {
  const unavailable: Admission = { ok: false, status: 503, message: UNAVAILABLE };
  const base = platformUrl.replace(/\/+$/, "");
  if (!base) return unavailable;
  const url = `${base}/authz/projects/${encodeURIComponent(project)}?want=${encodeURIComponent(method.toUpperCase())}`;
  try {
    const response = await fetchImpl(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) return unavailable;
    const body = await response.json();
    if (body?.verdict === "allow" && body.status === 200) {
      return { ok: true, pid: body.pid, slug: body.slug, role: body.role, admin: body.admin, mayWrite: body.may_write };
    }
    if (REFUSALS.has(body?.status) && typeof body.message === "string") {
      return { ok: false, status: body.status, message: body.message };
    }
    return unavailable;
  } catch {
    return unavailable;
  }
}
