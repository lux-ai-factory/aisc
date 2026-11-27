/**
 * Whether the AI card changed since a page was drawn, and who changed it when: the TypeScript reader of the
 * project database's work.card_change().
 *
 * A page drawn on one card state (card version, revision) shows "The AI card changed since you started (who,
 * when)" when it is no longer the latest (docs/specs/who-does-what.md, section 3). The page keeps the state it
 * was drawn on; a small read of the latest one, now and then, says whether it moved.
 *
 * Vendored into each Next.js app as src/vendor/aisc-access/cardChange.ts;
 * a test in each app fails when its copy differs from this one.
 */

/** The latest card state, with who stored its card (null when not recorded) and when (ISO time). */
export type CardChange = { version: string; number: number; revision: number; by: string | null; at: string };

/** The card state a page was drawn on. */
export type DrawnCardState = { version: string; revision: number };

type RawSql = (query: TemplateStringsArray, ...values: unknown[]) => Promise<unknown>;

/** The project's latest card state, or null while it has no card version. */
export async function cardChange(tx: { $queryRaw: RawSql }): Promise<CardChange | null> {
  const rows = (await tx.$queryRaw`SELECT work.card_change() AS change`) as { change: CardChange | null }[];
  return rows[0]?.change ?? null;
}

/** "11:02 UTC": the time of an ISO instant, in UTC, to the minute. */
function clock(at: string): string {
  return `${new Date(at).toISOString().slice(11, 16)} UTC`;
}

/** The banner for a page drawn on `drawn` (null: before the project had a card) when `now` is not that state;
 *  null while it is. */
export function cardChangedSince(drawn: DrawnCardState | null, now: CardChange | null): string | null {
  if (now === null) return null;
  if (drawn && drawn.version === now.version && drawn.revision === now.revision) return null;
  const said = [now.by, clock(now.at)].filter(Boolean).join(", ");
  return `The AI card changed since you started (${said}).`;
}
