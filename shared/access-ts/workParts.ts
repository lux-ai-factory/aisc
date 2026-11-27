/**
 * Who holds the parts of a task, for a held page to show, and the page's Take and Release: the platform's
 * GET /projects/{p}/work/{kind}/{subject} and POST .../parts/{part}/take | release, called as the person using
 * the page (docs/specs/who-does-what.md, section 7).
 *
 * Nothing is decided here: what the person may do on each part is the platform's answer (can_take,
 * can_release), and a refusal is the platform's own words.
 *
 * Vendored into each Next.js app as src/vendor/aisc-access/workParts.ts;
 * a test in each app fails when its copy differs from this one.
 */

/** One part as a held page shows it. */
export type HeldPart = {
  key: string;
  label: string;
  holderName: string | null;
  since: string | null;
  yours: boolean;
  canTake: boolean;
  canRelease: boolean;
};

/** The task's parts; `on` is whether the project holds parts at all (work.setting). */
export type HeldTask = { on: boolean; state: string; parts: HeldPart[] };

/** The task, or null while it does not exist (the first save makes it); or why it could not be read. */
export type PartsAnswer = { ok: true; task: HeldTask | null } | { ok: false; message: string };

export type ChangeAnswer = { ok: true } | { ok: false; message: string };

export type PlatformOptions = { platformUrl: string; token: string | null; fetchImpl?: typeof fetch };

const SILENT = "The platform did not answer.";
const TIMEOUT_MS = 10_000;

type RawPart = {
  key: string; label: string; holder_name: string | null; since: string | null; yours?: boolean;
  can_take?: boolean; can_release?: boolean;
};

function taskUrl(project: string, kind: string, subject: string, opts: PlatformOptions): string {
  const base = opts.platformUrl.replace(/\/+$/, "");
  return `${base}/projects/${[project, "work", kind, subject].map(encodeURIComponent).join("/")}`;
}

function headers(opts: PlatformOptions): Record<string, string> {
  return opts.token ? { Authorization: `Bearer ${opts.token}` } : {};
}

/** The platform's words in a refusal: its sentence, its refusal object's message, or its field errors. */
function wordsOf(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  if (Array.isArray(detail) && detail.length) {
    return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : String(e))).join("; ");
  }
  return `The platform refused (HTTP ${status}).`;
}

async function call(url: string, method: "GET" | "POST", opts: PlatformOptions) {
  const response = await (opts.fetchImpl ?? fetch)(url, {
    method,
    headers: headers(opts),
    cache: "no-store",
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  return { status: response.status, ok: response.ok, body: await response.json().catch(() => null) };
}

export async function readParts(project: string, kind: string, subject: string,
                                opts: PlatformOptions): Promise<PartsAnswer> {
  let answer;
  try {
    answer = await call(taskUrl(project, kind, subject, opts), "GET", opts);
  } catch {
    return { ok: false, message: SILENT };
  }
  if (answer.status === 404 && (answer.body as { detail?: unknown } | null)?.detail === "No such task.") {
    return { ok: true, task: null };
  }
  if (!answer.ok) return { ok: false, message: wordsOf(answer.body, answer.status) };
  const body = answer.body as { holding?: boolean; state?: string; parts?: RawPart[] };
  return {
    ok: true,
    task: {
      on: Boolean(body.holding),
      state: String(body.state ?? ""),
      parts: (body.parts ?? []).map((p) => ({
        key: p.key, label: p.label, holderName: p.holder_name, since: p.since, yours: Boolean(p.yours),
        canTake: Boolean(p.can_take), canRelease: Boolean(p.can_release),
      })),
    },
  };
}

export async function changePart(project: string, kind: string, subject: string, part: string,
                                 action: "take" | "release", opts: PlatformOptions): Promise<ChangeAnswer> {
  let answer;
  try {
    answer = await call(`${taskUrl(project, kind, subject, opts)}/parts/${encodeURIComponent(part)}/${action}`,
                        "POST", opts);
  } catch {
    return { ok: false, message: SILENT };
  }
  return answer.ok ? { ok: true } : { ok: false, message: wordsOf(answer.body, answer.status) };
}

/** "2026-11-27 10:40 UTC": an ISO instant in UTC, to the minute. */
function clock(at: string): string {
  return `${new Date(at).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/** "Governance: Bob Rossi holds it since 2026-11-27 10:40 UTC." */
export function holderLine(part: HeldPart): string {
  if (!part.holderName) return `${part.label}: nobody holds it.`;
  const since = part.since ? ` since ${clock(part.since)}` : "";
  return part.yours ? `${part.label}: you hold it${since}.` : `${part.label}: ${part.holderName} holds it${since}.`;
}
