/**
 * 投递队列准入徽标的回归测试。
 *
 * 覆盖修复 B：后端可能返回 `admission === null` 且 `requires_confirm === true`（例如匹配分析
 * 结论为空时，"需逐条确认"是后端准入判定的一部分）。此时徽标必须如实展示「需逐条确认」，
 * 不能因为 `admission` 为空就一律显示「未分析」而吞掉这个准入要求。
 */
import { App as AntdApp } from "antd";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyQueueItem } from "../../types";
import ApplyQueuePanel from "./ApplyQueuePanel";

const apiMocks = vi.hoisted(() => ({
  listQueue: vi.fn(),
  createApplyTask: vi.fn(),
  reorderQueue: vi.fn(),
  removeQueueItem: vi.fn(),
  updateQueueItem: vi.fn(),
  previewGreeting: vi.fn(),
  listResumes: vi.fn(),
}));

vi.mock("../../api/apply", () => ({
  listQueue: apiMocks.listQueue,
  createApplyTask: apiMocks.createApplyTask,
  reorderQueue: apiMocks.reorderQueue,
  removeQueueItem: apiMocks.removeQueueItem,
  updateQueueItem: apiMocks.updateQueueItem,
  previewGreeting: apiMocks.previewGreeting,
  QueueConflictError: class QueueConflictError extends Error {},
}));

vi.mock("../../api/resumes", () => ({
  listResumes: apiMocks.listResumes,
}));

const BASE_ITEM: ApplyQueueItem = {
  id: 1,
  job_id: 11,
  job_title: "后端开发",
  company: "A公司",
  resume_id: null,
  resume_title: "",
  greeting: "",
  sort_order: 0,
  status: "pending",
  admission: null,
  hard_gate: null,
  requires_confirm: false,
  created_at: "2026-09-17T08:00:00",
  updated_at: "2026-09-17T08:00:00",
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.listQueue.mockResolvedValue([]);
  apiMocks.listResumes.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ApplyQueuePanel 准入徽标", () => {
  it("admission 为空但 requires_confirm 为真时展示「需逐条确认」而非「未分析」", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...BASE_ITEM, admission: null, requires_confirm: true },
    ]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("需逐条确认")).toBeInTheDocument();
    expect(screen.queryByText("未分析")).not.toBeInTheDocument();
  });

  it("admission 为空且无需确认时展示「未分析」", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...BASE_ITEM, admission: null, requires_confirm: false },
    ]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("未分析")).toBeInTheDocument();
    expect(screen.queryByText("需逐条确认")).not.toBeInTheDocument();
  });

  it("有明确结论时保留原徽标，并叠加「需逐条确认」", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...BASE_ITEM, admission: "needs_confirm", requires_confirm: true },
    ]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("需确认")).toBeInTheDocument();
    expect(screen.getByText("需逐条确认")).toBeInTheDocument();
  });
});
