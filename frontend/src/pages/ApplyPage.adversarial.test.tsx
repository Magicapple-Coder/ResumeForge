/**
 * 投递台对抗性用例：暂停/继续/停止交互、队列准入拦截分支、显式开始投递的请求形态。
 *
 * 关键不变量：前端**只读**后端返回的 admission / requires_confirm，不自行再判一次；
 * 未勾选任何岗位时必须走 use_queue（"整队列顺序投递"），勾选后必须只投选中的那几
 * ——这对应 PRD 的"显式选择岗位"安全前提。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyQueueItem, ApplyTask, ApplyTaskDetail } from "../types";
import ApplyPage from "./ApplyPage";

const apiMocks = vi.hoisted(() => ({
  getBrowserStatus: vi.fn(),
  startBrowser: vi.fn(),
  stopBrowser: vi.fn(),
  listQueue: vi.fn(),
  createApplyTask: vi.fn(),
  reorderQueue: vi.fn(),
  removeQueueItem: vi.fn(),
  updateQueueItem: vi.fn(),
  previewGreeting: vi.fn(),
  getCurrentTask: vi.fn(),
  getTaskDetail: vi.fn(),
  getCollectTaskDetail: vi.fn(),
  pauseTask: vi.fn(),
  resumeTask: vi.fn(),
  stopTask: vi.fn(),
  listRecords: vi.fn(),
  retryRecord: vi.fn(),
  getApplyConfig: vi.fn(),
  updateApplyConfig: vi.fn(),
  getCollectConfig: vi.fn(),
  updateCollectConfig: vi.fn(),
  createCollectTask: vi.fn(),
  listSites: vi.fn(),
  getSiteHealth: vi.fn(),
}));

vi.mock("../api/apply", () => ({
  ...apiMocks,
  QueueConflictError: class QueueConflictError extends Error {},
}));

vi.mock("../api/resumes", () => ({
  listResumes: vi.fn(async () => ({ items: [], total: 0 })),
}));

const BROWSER = {
  state: "stopped" as const,
  port: 9333,
  profile_dir: "",
  browser_path: "",
  browser_name: "",
  logged_in_hint: "",
};

const SITES = {
  current: "boss",
  sites: [
    {
      key: "boss",
      display_name: "BOSS直聘",
      host: "zhipin.com",
      entry_url: "https://www.zhipin.com/",
      supports_collect: true,
      supports_apply: true,
    },
  ],
};

function queueItem(overrides: Partial<ApplyQueueItem>): ApplyQueueItem {
  return {
    id: 1,
    job_id: 11,
    job_title: "后端开发",
    company: "A公司",
    resume_id: null,
    resume_title: "",
    greeting: "",
    sort_order: 0,
    status: "pending",
    admission: "allow",
    hard_gate: "met",
    requires_confirm: false,
    created_at: "2026-09-18T08:00:00",
    updated_at: "2026-09-18T08:00:00",
    ...overrides,
  };
}

function task(status: ApplyTask["status"]): ApplyTask {
  return {
    id: 7,
    kind: "apply",
    status,
    total: 2,
    processed: 1,
    succeeded: 1,
    failed: 0,
    skipped: 0,
    current_step: "filling",
    stop_reason: "",
    config: {},
    message: "",
    started_at: "2026-09-18T08:00:00",
    finished_at: null,
    created_at: "2026-09-18T08:00:00",
  };
}

function detail(status: ApplyTask["status"]): ApplyTaskDetail {
  return { ...task(status), items: [] };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getBrowserStatus.mockResolvedValue(BROWSER);
  apiMocks.listQueue.mockResolvedValue([]);
  apiMocks.getCurrentTask.mockResolvedValue(null);
  apiMocks.listRecords.mockResolvedValue({ items: [], total: 0 });
  apiMocks.getApplyConfig.mockResolvedValue({});
  apiMocks.getCollectConfig.mockResolvedValue({ defaults: {} });
  apiMocks.listSites.mockResolvedValue(SITES);
  apiMocks.getSiteHealth.mockResolvedValue({ sites: [] });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ApplyPage 暂停 / 继续 交互", () => {
  it("offers 暂停 while running and calls the pause endpoint", async () => {
    apiMocks.getCurrentTask.mockResolvedValue(task("running"));
    apiMocks.getTaskDetail.mockResolvedValue(detail("running"));
    apiMocks.pauseTask.mockResolvedValue({ ...task("running"), status: "paused" });

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    const pause = await screen.findByRole("button", { name: /暂停/ });
    expect(pause).toBeEnabled();
    // 运行中不能点"继续"。
    expect(screen.getByRole("button", { name: /继续/ })).toBeDisabled();

    fireEvent.click(pause);
    await waitFor(() => expect(apiMocks.pauseTask).toHaveBeenCalledWith(7));
  });

  it("offers 继续 while paused and calls the resume endpoint", async () => {
    apiMocks.getCurrentTask.mockResolvedValue(task("paused"));
    apiMocks.getTaskDetail.mockResolvedValue(detail("paused"));
    apiMocks.resumeTask.mockResolvedValue({ ...task("running"), status: "running" });

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    const resume = await screen.findByRole("button", { name: /继续/ });
    expect(resume).toBeEnabled();
    expect(screen.getByRole("button", { name: /暂停/ })).toBeDisabled();

    fireEvent.click(resume);
    await waitFor(() => expect(apiMocks.resumeTask).toHaveBeenCalledWith(7));
  });
});

describe("投递队列准入拦截分支", () => {
  it("renders 不投 / 需逐条确认 / 未分析 for the three admission shapes", async () => {
    apiMocks.listQueue.mockResolvedValue([
      queueItem({ id: 1, job_id: 11, job_title: "真实缺口岗", admission: "block" }),
      queueItem({
        id: 2,
        job_id: 12,
        job_title: "需确认岗",
        admission: "needs_confirm",
        requires_confirm: true,
      }),
      queueItem({ id: 3, job_id: 13, job_title: "未分析岗", admission: null }),
    ]);

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    expect(await screen.findByText("不投")).toBeInTheDocument();
    expect(screen.getByText("需逐条确认")).toBeInTheDocument();
    expect(screen.getByText("未分析")).toBeInTheDocument();
  });

  it("starts the whole queue when nothing is selected (use_queue=true)", async () => {
    apiMocks.listQueue.mockResolvedValue([
      queueItem({ id: 1, job_id: 11 }),
      queueItem({ id: 2, job_id: 12, job_title: "数据开发" }),
    ]);
    apiMocks.createApplyTask.mockResolvedValue(task("running"));

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    const start = await screen.findByRole("button", { name: /开始投递/ });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);

    await waitFor(() => expect(apiMocks.createApplyTask).toHaveBeenCalledWith({ use_queue: true }));
  });

  it("disables 开始投递 when a task is already running", async () => {
    apiMocks.getCurrentTask.mockResolvedValue(task("running"));
    apiMocks.getTaskDetail.mockResolvedValue(detail("running"));
    apiMocks.listQueue.mockResolvedValue([queueItem({ id: 1, job_id: 11 })]);

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    const start = await screen.findByRole("button", { name: /开始投递/ });
    await waitFor(() => expect(start).toBeDisabled());
  });
});
