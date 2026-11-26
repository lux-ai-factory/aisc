/**
 * The lock that guards a project's card state (card version, revision): the TypeScript twin of
 * aisc_identity.card_lock, and with it the only place that spells the key.
 *
 * The card state moves when qualification stores a card. The transaction that stores one takes the lock
 * exclusive; every writer that reads "the latest card" to stamp a record, or to compare it with what a page
 * sent, takes it shared in its own transaction before it reads. The key is the one the platform's version
 * counter takes, hashtext('project.system'), in the project's database. Both are transaction locks: they end
 * with the transaction and need no release. Taken on a client outside a transaction they would end at once
 * and guard nothing, so both refuse a client that can still open a transaction ($transaction): Prisma hands
 * an interactive transaction a client without it.
 *
 * Vendored into each Next.js app as src/vendor/aisc-access/cardLock.ts;
 * a test in each app fails when its copy differs from this one.
 */

type RawSql = (query: TemplateStringsArray, ...values: unknown[]) => Promise<unknown>;
/** The part of a Prisma transaction client the locks use. */
export type CardLockTx = { $queryRaw?: RawSql; $executeRaw?: RawSql; $transaction?: unknown };

export class NotInTransaction extends Error {
  constructor() {
    super("the card lock is a transaction lock: take it inside a transaction");
    this.name = "NotInTransaction";
  }
}

function inTransaction(tx: CardLockTx): void {
  if ("$transaction" in tx) throw new NotInTransaction();
}

/** Take the card lock exclusive: for the transaction that stores a card. Nothing to read back, so $executeRaw. */
export async function cardLockExclusive(tx: Pick<Required<CardLockTx>, "$executeRaw">): Promise<void> {
  inTransaction(tx);
  await tx.$executeRaw`SELECT pg_advisory_xact_lock(hashtext('project.system'))`;
}

/**
 * Take the card lock shared: for a transaction that reads the latest card to stamp or compare it. Read
 * through $queryRaw, which cannot read the lock's void, hence the select around it.
 */
export async function cardLockShared(tx: Pick<Required<CardLockTx>, "$queryRaw">): Promise<void> {
  inTransaction(tx);
  await tx.$queryRaw`SELECT 1 AS locked FROM (SELECT pg_advisory_xact_lock_shared(hashtext('project.system'))) l`;
}
