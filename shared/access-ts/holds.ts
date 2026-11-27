/**
 * Saving on a part of a task: the TypeScript twin of aisc_identity.holds.
 *
 * One person holds a part at a time, and only that person saves on it. Every save on the content of a part
 * calls claimForSave inside the Prisma transaction that writes, before it writes. The database function
 * work.claim_for_save does the work: while the project's holding switch is off it does nothing; while it is
 * on, the first save on a part nobody holds takes it, the holder passes, and anyone else is refused (SQLSTATE
 * AH001, with the holder and since as DETAIL), as is any save on a task in check (AH002, with who submitted it
 * and when as DETAIL). The hold row is read FOR SHARE, so a take-over waits for this save to commit.
 *
 * A refused save throws HoldRefused, whose `refusal` is the refusal object the page shows; the transaction is
 * rolled back, so nothing of the save is written. The wording is one case file,
 * shared/identity/hold-refusal-cases.json, which this file's test and the Python tests both run.
 *
 * Vendored into each Next.js app as src/vendor/aisc-access/holds.ts;
 * a test in each app fails when its copy differs from this one.
 */
import type { Refusal } from "./refusal";

type RawSql = (query: TemplateStringsArray, ...values: unknown[]) => Promise<unknown>;
/** The part of a Prisma transaction client the claim uses. */
export type ClaimTx = { $executeRaw: RawSql; $transaction?: unknown };

const NOT_HOLDER = "AH001";
const NOT_FINAL = "AH002";

export class NotInTransaction extends Error {
  constructor() {
    super("a claim guards the write only inside the transaction that writes");
    this.name = "NotInTransaction";
  }
}

/** The save may not be written; `refusal` says why, in the words the page shows. */
export class HoldRefused extends Error {
  constructor(readonly refusal: Refusal) {
    super(refusal.message);
    this.name = "HoldRefused";
  }
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const two = (n: number) => String(n).padStart(2, "0");
const utcSeconds = (moment: Date) => moment.toISOString().replace(/\.\d{3}Z$/, "Z");

/** The time alone when it is today (UTC), else the day and the time. */
function since(moment: Date, now: Date): string {
  const time = `${two(moment.getUTCHours())}:${two(moment.getUTCMinutes())} UTC`;
  return moment.toISOString().slice(0, 10) === now.toISOString().slice(0, 10)
    ? time
    : `${moment.getUTCDate()} ${MONTHS[moment.getUTCMonth()]} ${time}`;
}

/**
 * The refusal a database error of work.claim_for_save stands for, or null for any other error. `detail` is
 * the error's DETAIL text, `label` the part as the page names it.
 */
export function refusalFor(
  sqlstate: string | null,
  detail: string | null,
  { label, personName, now = new Date() }: { label: string; personName: string; now?: Date },
): Refusal | null {
  if (sqlstate === NOT_HOLDER) {
    const held = JSON.parse(detail ?? "{}") as { holder?: string | null; since?: string | null };
    const holder = held.holder || "Someone";
    const from = held.since ? new Date(held.since) : now;
    return {
      code: "not_holder",
      what: label,
      message:
        `${holder} holds ${label} since ${since(from, now)}. Your text is kept below;` +
        " ask them to hand it over, or an owner to give it to you.",
      changed: [],
      saved: [],
      not_saved: [],
      current: { token: "", changed_by: holder, changed_at: utcSeconds(from), values: {} },
    };
  }
  if (sqlstate === NOT_FINAL) {
    const submitted = JSON.parse(detail ?? "{}") as { submitted_by?: string | null; submitted_at?: string | null };
    if (submitted.submitted_by && submitted.submitted_at) {
      const at = new Date(submitted.submitted_at);
      return {
        code: "not_final",
        what: label,
        message:
          `${submitted.submitted_by} submitted ${label} for check at ${since(at, now)},` +
          " and its content does not change while it is checked. Your text is kept below.",
        changed: [],
        saved: [],
        not_saved: [],
        current: { token: "", changed_by: submitted.submitted_by, changed_at: utcSeconds(at), values: {} },
      };
    }
    return {
      code: "not_final",
      what: label,
      message: `${label} is in check, and its content does not change while it is checked. Your text is kept below.`,
      changed: [],
      saved: [],
      not_saved: [],
      current: { token: "", changed_by: personName, changed_at: utcSeconds(now), values: {} },
    };
  }
  return null;
}

/** The SQLSTATE and DETAIL of what Prisma throws for an error a raw query raised. */
function databaseError(error: unknown): { sqlstate: string | null; detail: string | null } {
  const meta = (error as { meta?: { code?: unknown; message?: unknown } } | null)?.meta;
  const sqlstate = typeof meta?.code === "string" ? meta.code : null;
  const message = typeof meta?.message === "string" ? meta.message : "";
  const at = message.indexOf("\nDETAIL: ");
  return { sqlstate, detail: at < 0 ? null : message.slice(at + "\nDETAIL: ".length).split("\n")[0] };
}

/**
 * Claim `part` of the task (`kind`, `subject`) for the person saving, inside the transaction that writes.
 * Throws HoldRefused when the save may not be written. Nothing to read back, so $executeRaw.
 */
export async function claimForSave(
  tx: ClaimTx,
  kind: string,
  subject: string,
  part: string,
  label: string,
  personSubject: string,
  personName: string,
): Promise<void> {
  if ("$transaction" in tx) throw new NotInTransaction();
  try {
    await tx.$executeRaw`SELECT work.claim_for_save(${kind}, ${subject}, ${part}, ${label}, ${personSubject}, ${personName})`;
  } catch (error) {
    const { sqlstate, detail } = databaseError(error);
    const refusal = refusalFor(sqlstate, detail, { label, personName });
    if (refusal === null) throw error;
    throw new HoldRefused(refusal);
  }
}
