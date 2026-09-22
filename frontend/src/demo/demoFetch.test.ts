/**
 * 在线体验拦截层的测试。
 *
 * 这一层的每条分支都对应一种「用户会看到什么」，所以逐条钉住：
 * 命中快照回放、未命中给空态、写操作给中文只读提示、AI 流式按节奏回放。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEMO_WRITE_MESSAGE,
  installDemoFetch,
  loadDemoData,
  lookup,
  normalizeKey,
  pickReply,
  __getLoadedRoutes,
} from "./demoFetch";

/** 造一份最小快照，塞进模块内部状态。 */
function seedSnapshot(routes: Record<string, { status: number; body: unknown }>) {
  return loadDemoData({
    snapshotUrl: `data:application/json,${encodeURIComponent(JSON.stringify({ routes }))}`,
    aiRepliesUrl: `data:application/json,${encodeURIComponent(
      JSON.stringify({
        replies: [
          { match: ["台账"], text: "台账回放内容" },
          { match: [], text: "兜底回放内容" },
        ],
        resumeDraft: "简历草稿回放",
      }),
    )}`,
  });
}

let uninstall: (() => void) | undefined;

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  uninstall?.();
  uninstall = undefined;
});

describe("normalizeKey", () => {
  it("保留 pathname 与 query，丢掉 origin", () => {
    expect(normalizeKey("http://localhost:5199/api/jobs?page=1&page_size=10")).toBe(
      "/api/jobs?page=1&page_size=10",
    );
  });

  it("相对路径原样保留", () => {
    expect(normalizeKey("/api/stats")).toBe("/api/stats");
  });
});

describe("lookup 的匹配梯度", () => {
  beforeEach(async () => {
    await seedSnapshot({
      "/api/jobs?page=1&page_size=10": { status: 200, body: { items: [1] } },
      "/api/tracker": { status: 200, body: { items: [2] } },
    });
  });

  it("精确命中（含 query）", () => {
    expect(lookup("/api/jobs?page=1&page_size=10")).toEqual({ status: 200, body: { items: [1] } });
  });

  it("query 不同时退到同路径的任意快照", () => {
    // 录制时只覆盖了 page_size=10，用户改了每页条数时不应该变成空态。
    expect(lookup("/api/jobs?page=2&page_size=50")).toEqual({
      status: 200,
      body: { items: [1] },
    });
  });

  it("无 query 的路径精确命中", () => {
    expect(lookup("/api/tracker")).toEqual({ status: 200, body: { items: [2] } });
  });

  it("完全未录制返回 undefined", () => {
    expect(lookup("/api/nonexistent")).toBeUndefined();
  });
});

describe("pickReply", () => {
  beforeEach(async () => {
    await seedSnapshot({});
  });

  it("按关键词命中", () => {
    expect(pickReply("这条台账的数字站得住吗")).toBe("台账回放内容");
  });

  it("没有关键词时走兜底", () => {
    expect(pickReply("随便问点什么")).toBe("兜底回放内容");
  });

  it("空输入也走兜底而不是抛错", () => {
    expect(pickReply("")).toBe("兜底回放内容");
  });
});

describe("installDemoFetch", () => {
  beforeEach(async () => {
    await seedSnapshot({
      "/api/stats": { status: 200, body: { jobs: 14 } },
      "/api/jobs/parse-text": { status: 200, body: { title: "解析结果" } },
    });
    uninstall = installDemoFetch();
  });

  it("只读 GET 回放快照", async () => {
    const resp = await fetch("/api/stats");
    expect(resp.status).toBe(200);
    expect(await resp.json()).toEqual({ jobs: 14 });
  });

  it("未录制的 GET 回 404 空态而不是抛网络错误", async () => {
    const resp = await fetch("/api/unknown");
    expect(resp.status).toBe(404);
    expect((await resp.json()).detail).toContain("在线体验版");
  });

  it("写操作回 403 与中文只读提示", async () => {
    const resp = await fetch("/api/claims", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "x" }),
    });
    expect(resp.status).toBe(403);
    expect((await resp.json()).detail).toBe(DEMO_WRITE_MESSAGE);
  });

  it("只计算不落库的 POST 走快照回放（在白名单里）", async () => {
    const resp = await fetch("/api/jobs/parse-text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "某岗位" }),
    });
    expect(resp.status).toBe(200);
    expect(await resp.json()).toEqual({ title: "解析结果" });
  });

  it("DELETE 也被拦下", async () => {
    const resp = await fetch("/api/jobs/1", { method: "DELETE" });
    expect(resp.status).toBe(403);
  });

  it("非 API 路径原样放行给原始 fetch", async () => {
    const original = window.fetch;
    const spy = vi.fn().mockResolvedValue(new Response("asset", { status: 200 }));
    window.fetch = spy;
    try {
      // 重新安装，让拦截层包住这个 spy
      const undo = installDemoFetch();
      await fetch("/assets/index.js");
      expect(spy).toHaveBeenCalled();
      undo();
    } finally {
      window.fetch = original;
    }
  });

  it("卸载后恢复原始 fetch", async () => {
    const before = window.fetch;
    uninstall?.();
    uninstall = undefined;
    expect(window.fetch).not.toBe(before);
  });
});

describe("AI 流式回放", () => {
  beforeEach(async () => {
    await seedSnapshot({});
    uninstall = installDemoFetch();
  });

  it("助手消息接口吐出 SSE 事件，内容是命中的回放", async () => {
    const resp = await fetch("/api/assistant/conversations/3/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: "台账里的数字站得住吗" }),
    });
    expect(resp.status).toBe(200);
    expect(resp.headers.get("content-type")).toContain("text/event-stream");

    const text = await resp.text();
    // SSE 帧格式必须是 `data: {json}\n\n`，否则 api/stream.ts 收不到事件。
    expect(text).toContain("data: ");
    const payloads = text
      .split("\n\n")
      .filter((block) => block.startsWith("data: "))
      .map((block) => JSON.parse(block.slice("data: ".length)));
    expect(payloads.length).toBeGreaterThan(1);
    const joined = payloads.map((p) => p.content).join("");
    expect(joined).toBe("台账回放内容");
    expect(payloads[payloads.length - 1].type).toBe("done");
  });

  it("简历生成接口也能回放", async () => {
    const resp = await fetch("/api/resumes/generate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: 6 }),
    });
    expect(resp.status).toBe(200);
    const text = await resp.text();
    expect(text).toContain("data: ");
    expect(text).toContain("done");
  });
});

describe("loadDemoData", () => {
  it("载入后路由表可读", async () => {
    await seedSnapshot({ "/api/stats": { status: 200, body: { ok: true } } });
    expect(Object.keys(__getLoadedRoutes())).toContain("/api/stats");
  });

  it("快照地址不可用时抛出，调用方据此走降级", async () => {
    await expect(
      loadDemoData({
        snapshotUrl: "/definitely-not-here.json",
        aiRepliesUrl: "/definitely-not-here.json",
      }),
    ).rejects.toThrow();
  });
});
