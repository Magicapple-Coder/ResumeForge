import { afterEach, describe, expect, it, vi } from "vitest";
import type { AssistantSkill } from "../types";
import { importSkill } from "./skill";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SAVED: AssistantSkill = {
  id: 1,
  name: "面试追问",
  description: "",
  enabled: true,
  source_name: "面试追问.md",
  prompt_chars: 20,
  files: [],
  updated_at: "2026-09-16T00:00:00",
};

function stubFetch() {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(SAVED), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("importSkill", () => {
  it("tells the backend the original filename", async () => {
    const fetchMock = stubFetch();

    await importSkill(new File(["提示词"], "面试追问.md", { type: "text/markdown" }));

    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    // 头只能放 latin-1，中文文件名必须先编码，否则 fetch 会直接抛错。
    expect(headers.get("X-Skill-Filename")).toBe(encodeURIComponent("面试追问.md"));
  });

  it("sends the file itself, typed by extension rather than by the browser", async () => {
    const fetchMock = stubFetch();
    const zip = new File(["PK"], "面试追问.zip", { type: "application/octet-stream" });

    await importSkill(zip);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toMatchObject({ "Content-Type": "application/zip" });
    expect(init.body).toBe(zip);
  });

  it("surfaces the backend's reason when the import is rejected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "技能包里需要有且只有一份提示词" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(importSkill(new File(["x"], "坏包.zip"))).rejects.toThrow(
      "技能包里需要有且只有一份提示词",
    );
  });
});
