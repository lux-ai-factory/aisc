// Run from each Next.js app, where this file is vendored as test/vendor/workParts.test.ts next to
// src/vendor/aisc-access/workParts.ts.
import { describe, expect, it, vi } from "vitest";
import { changePart, holderLine, readParts } from "@/vendor/aisc-access/workParts";

// On every held page: who holds this part, a Take button when nobody does, and Release for the holder
// (docs/specs/who-does-what.md, section 7). The page reads the task from the platform as the person using it;
// what they may do on each part is the platform's to say (can_take, can_release). A refusal is said in the
// platform's words. The answers below have the shape platform/tests/test_api_work_pages.py holds the platform to.

const OPTS = { platformUrl: "http://platform:8000/", token: "tok" };

function answering(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });
}

const TASK = {
  kind: "fill_checklist", subject: "s1", state: "open", round: 1, holding: true,
  parts: [
    { key: "governance", label: "Governance", holder_subject: "bob", holder_name: "Bob Rossi",
      since: "2026-11-27T10:40:00+00:00", offered_to_subject: null, yours: false, can_take: false,
      can_release: false, can_take_over: false },
    { key: "data", label: "Data", holder_subject: null, holder_name: null, since: null, offered_to_subject: null,
      yours: false, can_take: true, can_release: false, can_take_over: false },
    { key: "scope", label: "Scope", holder_subject: "me", holder_name: "Me", since: "2026-11-27T09:00:00+00:00",
      offered_to_subject: null, yours: true, can_take: false, can_release: true, can_take_over: false },
  ],
};

describe("reading who holds the parts of a task", () => {
  it("asks the platform for the task as the person using the page", async () => {
    const fetchImpl = answering(200, TASK);
    await readParts("demo", "fill_checklist", "s1", { ...OPTS, fetchImpl });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://platform:8000/projects/demo/work/fill_checklist/s1");
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("gives each part's holder, since when, and what the person may do, as the platform said", async () => {
    const got = await readParts("demo", "fill_checklist", "s1", { ...OPTS, fetchImpl: answering(200, TASK) });
    expect(got).toEqual({
      ok: true,
      task: {
        on: true, state: "open",
        parts: [
          { key: "governance", label: "Governance", holderName: "Bob Rossi", since: "2026-11-27T10:40:00+00:00",
            yours: false, canTake: false, canRelease: false },
          { key: "data", label: "Data", holderName: null, since: null, yours: false, canTake: true,
            canRelease: false },
          { key: "scope", label: "Scope", holderName: "Me", since: "2026-11-27T09:00:00+00:00", yours: true,
            canTake: false, canRelease: true },
        ],
      },
    });
  });

  it("a task the platform does not have yet is no task: the first save makes it", async () => {
    const got = await readParts("demo", "fill_checklist", "s1",
      { ...OPTS, fetchImpl: answering(404, { detail: "No such task." }) });
    expect(got).toEqual({ ok: true, task: null });
  });

  it("any other refusal is said in the platform's words", async () => {
    const got = await readParts("demo", "fill_checklist", "s1",
      { ...OPTS, fetchImpl: answering(503, { detail: "The platform could not reach its database" }) });
    expect(got).toEqual({ ok: false, message: "The platform could not reach its database" });
  });

  it("a platform that does not answer says so", async () => {
    const got = await readParts("demo", "fill_checklist", "s1",
      { ...OPTS, fetchImpl: vi.fn().mockRejectedValue(new TypeError("fetch failed")) });
    expect(got.ok).toBe(false);
  });
});

describe("taking and releasing a part", () => {
  it("posts to the part's take or release as the person using the page", async () => {
    const fetchImpl = answering(200, {});
    expect(await changePart("demo", "fill_checklist", "s1", "data", "take", { ...OPTS, fetchImpl }))
      .toEqual({ ok: true });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://platform:8000/projects/demo/work/fill_checklist/s1/parts/data/take");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer tok");
    await changePart("demo", "fill_checklist", "s1", "scope", "release", { ...OPTS, fetchImpl });
    expect(fetchImpl.mock.calls[1][0]).toBe("http://platform:8000/projects/demo/work/fill_checklist/s1/parts/scope/release");
  });

  it("a refusal is the message of the platform's refusal object", async () => {
    const detail = { code: "not_holder", message: "Bob Rossi holds this part since 27 Nov 10:40.", current: {} };
    expect(await changePart("demo", "fill_checklist", "s1", "data", "take",
      { ...OPTS, fetchImpl: answering(409, { detail }) }))
      .toEqual({ ok: false, message: "Bob Rossi holds this part since 27 Nov 10:40." });
  });

  it("a refusal in a sentence is that sentence", async () => {
    expect(await changePart("demo", "fill_checklist", "s1", "data", "take",
      { ...OPTS, fetchImpl: answering(403, { detail: "This needs the editor role." }) }))
      .toEqual({ ok: false, message: "This needs the editor role." });
  });
});

describe("the line a held page shows for a part", () => {
  const part = { key: "k", label: "Governance", since: "2026-11-27T10:40:00+00:00", canTake: false, canRelease: false };
  it("names the holder and since when", () => {
    expect(holderLine({ ...part, holderName: "Bob Rossi", yours: false }))
      .toBe("Governance: Bob Rossi holds it since 2026-11-27 10:40 UTC.");
  });
  it("says when it is the person's own", () => {
    expect(holderLine({ ...part, holderName: "Me", yours: true }))
      .toBe("Governance: you hold it since 2026-11-27 10:40 UTC.");
  });
  it("says when nobody holds it", () => {
    expect(holderLine({ ...part, holderName: null, since: null, yours: false })).toBe("Governance: nobody holds it.");
  });
});
