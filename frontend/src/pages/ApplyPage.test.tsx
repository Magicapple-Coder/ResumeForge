import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyQueueItem, ApplyTask, ApplyTaskDetail, CollectConfigOut } from "../types";
import ApplyPage from "./ApplyPage";
import CollectPanel from "../components/apply/CollectPanel";

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
}));

vi.mock("../api/apply", () => ({
  ...apiMocks,
  QueueConflictError: class QueueConflictError extends Error {},
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

const QUEUE_ITEM: ApplyQueueItem = {
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
  created_at: "2026-09-17T08:00:00",
  updated_at: "2026-09-17T08:00:00",
};

function runningTask(): ApplyTask {
  return {
    id: 7,
    kind: "apply",
    status: "running",
    total: 2,
    processed: 1,
    succeeded: 1,
    failed: 0,
    skipped: 0,
    current_step: "filling",
    stop_reason: "",
    config: {},
    message: "",
    started_at: "2026-09-17T08:00:00",
    finished_at: null,
    created_at: "2026-09-17T08:00:00",
  };
}

function detail(overrides: Partial<ApplyTaskDetail> = {}): ApplyTaskDetail {
  return { ...runningTask(), items: [], ...overrides };
}

const COLLECT_CONFIG: CollectConfigOut = {
  keywords: ["后端"],
  city: "北京",
  salary_min: 20,
  experience: "",
  education: "",
  per_task_limit: 20,
  interval_seconds: 6,
  interval_jitter_seconds: 3,
  defaults: {
    keywords: [],
    city: "",
    salary_min: null,
    experience: "",
    education: "",
    per_task_limit: 20,
    interval_seconds: 6,
    interval_jitter_seconds: 3,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getBrowserStatus.mockResolvedValue(BROWSER);
  apiMocks.listQueue.mockResolvedValue([]);
  apiMocks.getCurrentTask.mockResolvedValue(null);
  apiMocks.listRecords.mockResolvedValue({ items: [], total: 0 });
  apiMocks.getApplyConfig.mockResolvedValue({});
  apiMocks.getCollectConfig.mockResolvedValue(COLLECT_CONFIG);
  apiMocks.listSites.mockResolvedValue(SITES);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ApplyPage", () => {
  it("shows an empty-state hint when the queue is empty", async () => {
    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    expect(await screen.findByText(/队列还是空的/)).toBeInTheDocument();
    // 浏览器状态条与「开始投递」入口始终在同一屏，用户不用去别处找。
    expect(screen.getByText("投递专用浏览器")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /开始投递/ })).toBeDisabled();
  });

  it("marks entries that need per-item confirmation and shows blocked ones as not-to-apply", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...QUEUE_ITEM, admission: "needs_confirm", requires_confirm: true },
      { ...QUEUE_ITEM, id: 2, job_id: 12, job_title: "算法工程", admission: "block" },
      { ...QUEUE_ITEM, id: 3, job_id: 13, job_title: "未分析岗", admission: null },
    ]);

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    expect(await screen.findByText("需逐条确认")).toBeInTheDocument();
    expect(screen.getAllByText("不投").length).toBeGreaterThan(0);
    expect(screen.getByText("未分析")).toBeInTheDocument();
    // 逐条操作按钮可键盘聚焦（有可读名称）。
    expect(screen.getByLabelText(/上移 后端开发/)).toBeInTheDocument();
  });

  it("announces the current job site coming from the backend, not a hardcoded name", async () => {
    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    expect(await screen.findByText(/当前招聘网站/)).toBeInTheDocument();
    expect(screen.getByText("BOSS直聘")).toBeInTheDocument();
    expect(screen.getByText(/目前仅支持这一个招聘网站/)).toBeInTheDocument();
  });

  it("keeps pause/stop reachable and calls the stop endpoint", async () => {
    apiMocks.getCurrentTask.mockResolvedValue(runningTask());
    apiMocks.getTaskDetail.mockResolvedValue(detail());
    apiMocks.stopTask.mockResolvedValue({ ...runningTask(), status: "stopped" });
    apiMocks.getCollectTaskDetail.mockResolvedValue(detail());

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    // 这条用例渲染的是整个投递台页面（五个面板 + 浏览器工具条），而 vitest 默认开满并行
    // worker，满载时首次渲染可能超过全局 5s 的 asyncUtilTimeout——单跑 4s、全量就超时。
    // 断言本身没问题，是预算太紧，所以这里给它一个明确的宽裕时间。
    const stop = await screen.findByRole("button", { name: /停止/ }, { timeout: 20_000 });
    expect(stop).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /暂停/ })).toBeEnabled();

    fireEvent.click(stop);

    await waitFor(() => expect(apiMocks.stopTask).toHaveBeenCalledWith(7));
  });

  it("raises a prominent banner when the batch is circuit-breaker paused", async () => {
    apiMocks.getCurrentTask.mockResolvedValue({ ...runningTask(), status: "breaker_paused" });
    apiMocks.getTaskDetail.mockResolvedValue(
      detail({
        status: "breaker_paused",
        stop_reason: "breaker",
        message: "已因连续 3 次失败自动暂停，请查看记录并处理后点击「继续」",
      }),
    );

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    expect(await screen.findByText(/自动暂停/)).toBeInTheDocument();
    expect(screen.getByText("熔断暂停")).toBeInTheDocument();
  });
});

describe("CollectPanel", () => {
  it("labels unmapped conditions as not-in-effect instead of silently dropping them", async () => {
    const collectTask = detail({
      kind: "collect",
      config: { unmapped_conditions: ["薪资", "学历"] },
    });

    render(
      <AntdApp>
        <CollectPanel disabled={false} onStarted={vi.fn()} collectTask={collectTask} />
      </AntdApp>,
    );

    // 断言范围限定在「未生效」提示条内：/薪资/ 在全页还会命中表单的「最低薪资（K）」标签，
    // 用 getByText 会命中多个元素。这里只关心提示条本身是否如实列出了未生效条件。
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("以下条件未生效");
    expect(banner).toHaveTextContent("薪资");
    expect(banner).toHaveTextContent("学历");
  });

  it("surfaces a load error instead of rendering a blank form", async () => {
    apiMocks.getCollectConfig.mockRejectedValue(new Error("加载采集条件失败"));

    render(
      <AntdApp>
        <CollectPanel disabled={false} onStarted={vi.fn()} collectTask={null} />
      </AntdApp>,
    );

    expect(await screen.findByText("加载采集条件失败")).toBeInTheDocument();
  });
});
