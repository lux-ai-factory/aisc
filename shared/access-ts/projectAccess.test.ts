// Run from each Next.js app, where this file is vendored as test/vendor/projectAccess.test.ts
// next to src/vendor/aisc-access/projectAccess.ts.
import { describe, expect, it, vi } from "vitest";
import { admit, isProjectId, projectFromPath, UNAVAILABLE } from "@/vendor/aisc-access/projectAccess";

const PLATFORM = "http://platform:8000";
const PID = "11111111-1111-4111-8111-111111111111";

function answering(body: unknown, init: { ok?: boolean; status?: number } = {}) {
  return vi.fn().mockResolvedValue({ ok: init.ok ?? true, status: init.status ?? 200, json: async () => body });
}

const allowed = {
  verdict: "allow", status: 200, message: null, pid: PID, slug: "alpha",
  role: "editor", admin: false, may_write: true,
};

describe("which project a request is inside", () => {
  it("reads the project out of the path", () => {
    expect(projectFromPath("/p/mcas/qualifications")).toBe("mcas");
    expect(projectFromPath("/p/mcas")).toBe("mcas");
  });

  it("decodes what the URL encoded, and leaves a malformed escape for the pid check", () => {
    expect(projectFromPath("/p/a%20b/x")).toBe("a b");
    expect(projectFromPath("/p/%E0%A4%A/x")).toBe("%E0%A4%A");
  });

  it("is null outside a project", () => {
    for (const path of ["/", "/methodology", "/p/", "/p"]) expect(projectFromPath(path)).toBeNull();
  });

  it("knows a pid from anything else", () => {
    expect(isProjectId(PID)).toBe(true);
    expect(isProjectId(PID.toUpperCase())).toBe(true);
    expect(isProjectId("alpha")).toBe(false);
    expect(isProjectId(`{${PID}}`)).toBe(false);
  });
});

describe("admit", () => {
  it("asks the platform about this project and this method, with the caller's token", async () => {
    const fetchImpl = answering(allowed);
    await admit(PID, "post", "a-token", { platformUrl: `${PLATFORM}/`, fetchImpl });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${PLATFORM}/authz/projects/${PID}?want=POST`);
    expect(init.headers.Authorization).toBe("Bearer a-token");
    expect(init.cache).toBe("no-store");
  });

  it("returns the project the platform admitted", async () => {
    const admission = await admit(PID, "POST", "t", { platformUrl: PLATFORM, fetchImpl: answering(allowed) });
    expect(admission).toEqual({ ok: true, pid: PID, slug: "alpha", role: "editor", admin: false, mayWrite: true });
  });

  it("passes the platform's refusal on as it is", async () => {
    const refusal = { ...allowed, verdict: "forbidden", status: 403, message: "You can read this project but not change it.",
      pid: null, slug: null, role: null, may_write: false };
    const admission = await admit(PID, "POST", "t", { platformUrl: PLATFORM, fetchImpl: answering(refusal) });
    expect(admission).toEqual({ ok: false, status: 403, message: "You can read this project but not change it." });
  });

  it("is 503 when the platform is not configured, unreachable, refusing, or answering nonsense", async () => {
    const cases = [
      { platformUrl: "", fetchImpl: vi.fn() },
      { platformUrl: PLATFORM, fetchImpl: vi.fn().mockRejectedValue(new Error("no route to host")) },
      { platformUrl: PLATFORM, fetchImpl: answering({}, { ok: false, status: 401 }) },
      { platformUrl: PLATFORM, fetchImpl: answering({ role: "editor", may_write: true }) },
      { platformUrl: PLATFORM, fetchImpl: answering({ ...allowed, status: 418 }) },
    ];
    for (const options of cases) {
      expect(await admit(PID, "GET", "t", options)).toEqual({ ok: false, status: 503, message: UNAVAILABLE });
    }
    expect(cases[0].fetchImpl).not.toHaveBeenCalled();
  });

  it("gives up on a platform that does not answer in time", async () => {
    const hanging = vi.fn((_url: string, init: { signal: AbortSignal }) =>
      new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(new Error("aborted")))));
    const admission = await admit(PID, "GET", "t", {
      platformUrl: PLATFORM,
      fetchImpl: hanging as unknown as typeof fetch,
      timeoutMs: 10,
    });
    expect(admission).toEqual({ ok: false, status: 503, message: UNAVAILABLE });
  });

  it("never sends an empty bearer header", async () => {
    const fetchImpl = answering(allowed);
    await admit(PID, "GET", null, { platformUrl: PLATFORM, fetchImpl });
    expect(fetchImpl.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });
});
