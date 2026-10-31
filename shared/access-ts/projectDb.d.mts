// Types for projectDb.mjs, which stays plain JavaScript so the apps' node scripts can import it.
export const PLACEHOLDER: "{database}";
export const PRISMA_OPTIONS: ReadonlySet<string>;
export const MAINTENANCE_DATABASE: "postgres";
export class NotAPid extends Error {}
export function databaseName(pid: string): string;
export function pidOf(name: string): string | null;
export function projectDsn(template: string, database: string, options?: { driver?: string | null }): string;
export function maintenanceDsn(template: string, options?: { driver?: string | null }): string;
