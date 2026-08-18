import { afterEach, describe, expect, it, vi } from "vitest";
import { buildQuery, request } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildQuery", () => {
  it("omits empty values and URL-encodes the rest", () => {
    expect(buildQuery({ keyword: "算法 工程师", page: 2, status: "", optional: undefined })).toBe(
      "?keyword=%E7%AE%97%E6%B3%95+%E5%B7%A5%E7%A8%8B%E5%B8%88&page=2",
    );
  });
});

describe("request", () => {
  it("keeps the JSON content type when adding custom headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await request("/example", { headers: { "X-Request-ID": "test-id" } });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-Request-ID")).toBe("test-id");
  });

  it("respects an explicit content type override", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await request("/example", { headers: { "Content-Type": "text/plain" } });

    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("Content-Type")).toBe("text/plain");
  });
});
