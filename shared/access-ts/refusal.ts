/**
 * The refusal: the answer to a save that would replace something the person has not seen. The TypeScript
 * twin of aisc_identity.refusal.
 *
 * Each app keeps its own error envelope (a server action's state: ok false, refusal, the posted values);
 * inside it a refusal is the same object everywhere. Its shape is held by shared/identity/refusal-cases.json,
 * which this file's test and the Python tests both run.
 *
 * Vendored into each Next.js app as src/vendor/aisc-access/refusal.ts;
 * a test in each app fails when its copy differs from this one.
 */

/** Each code and the HTTP status it is answered with. */
export const REFUSAL_STATUS = {
  changed_since_opened: 409, // someone saved this since the page was drawn
  upstream_moved: 409, // something the action depends on changed
  upstream_moved_confirm: 409, // only the card state moved; the person may confirm and go on
  already_exists: 409, // the thing to create is there, with other content
  cited_by_report: 409, // a stored report names this record
  syncing: 409, // the card is being synchronised; try again in a moment
  not_final: 409, // the action marks something complete and it is not
  token_required: 400, // a save without a token, on a write that needs one
  not_holder: 409, // someone else holds the part this save writes
  not_enough_checkers: 409, // fewer people are left to check the task than its kind needs
} as const;

export type RefusalCode = keyof typeof REFUSAL_STATUS;

export type Refusal = {
  code: RefusalCode;
  /** The thing, in the word the page uses for it. */
  what: string;
  /** One or two sentences a person can act on, naming the fields, the person and the time. */
  message: string;
  /** Labels of what the other save changed; empty when the app cannot tell. */
  changed: string[];
  /** For a form of independent items, which of this person's items were written and which were not. */
  saved: string[];
  not_saved: string[];
  current: {
    /** The token to send with the next save. */
    token: string;
    changed_by: string;
    /** UTC, to the second: 2026-01-20T14:32:10Z. */
    changed_at: string;
    /** The stored values of the items not saved; a secret is { secret: true }, never its value. */
    values: Record<string, unknown>;
  };
};

const UTC_SECONDS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isWords = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";
const isLabels = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((label) => typeof label === "string");

/** Whether `value` is a refusal of the shape every app answers. */
export function isRefusal(value: unknown): value is Refusal {
  if (!isObject(value)) return false;
  const { code, what, message, changed, saved, not_saved: notSaved, current } = value;
  if (typeof code !== "string" || !Object.prototype.hasOwnProperty.call(REFUSAL_STATUS, code)) return false;
  if (!isWords(what) || !isWords(message)) return false;
  if (!isLabels(changed) || !isLabels(saved) || !isLabels(notSaved)) return false;
  if (!isObject(current)) return false;
  return (
    typeof current.token === "string" &&
    isWords(current.changed_by) &&
    typeof current.changed_at === "string" &&
    UTC_SECONDS.test(current.changed_at) &&
    isObject(current.values)
  );
}
