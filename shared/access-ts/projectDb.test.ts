// Run from each Next.js app, where this file is vendored as test/vendor/projectDb.test.ts next to
// src/vendor/aisc-access/projectDb.mjs and the shared cases as test/fixtures/projectdb-cases.json
// (shared/identity, also run by aisc_identity.projectdb).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  databaseName,
  maintenanceDsn,
  NotAPid,
  pidOf,
  projectDsn,
} from "@/vendor/aisc-access/projectDb.mjs";

type Cases = {
  names: { pid: string; name?: string; refused?: boolean }[];
  pids: { name: string; pid: string | null }[];
  dsns: { name: string; template: string; database: string; driver?: string; dsn?: string; refused?: boolean }[];
};
const CASES = JSON.parse(
  readFileSync(new URL("../fixtures/projectdb-cases.json", import.meta.url), "utf8"),
) as Cases;

describe("a project's database", () => {
  it.each(CASES.names.map((c) => [JSON.stringify(c.pid), c] as const))("is named by its pid: %s", (_n, c) => {
    if (c.refused) expect(() => databaseName(c.pid)).toThrow(NotAPid);
    else expect(databaseName(c.pid)).toBe(c.name);
  });

  it.each(CASES.pids.map((c) => [c.name, c] as const))("gives back its pid: %s", (_n, c) => {
    expect(pidOf(c.name)).toBe(c.pid);
  });

  it.each(CASES.dsns.map((c) => [c.name, c] as const))("is reached through the template: %s", (_n, c) => {
    const make = () => projectDsn(c.template, c.database, { driver: c.driver ?? null });
    if (c.refused) expect(make).toThrow();
    else expect(make()).toBe(c.dsn);
  });

  it("is made from the maintenance database", () => {
    expect(maintenanceDsn("postgresql://reader:secret@postgres/{database}?sslmode=require")).toBe(
      "postgresql://reader:secret@postgres/postgres?sslmode=require",
    );
  });
});
