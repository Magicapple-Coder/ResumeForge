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
  getSiteHealth: vi.fn(),
  getCollectFilterOptions: vi.fn(),
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
  job_type: "",
  filters: {},
  per_task_limit: 20,
  interval_seconds: 6,
  interval_jitter_seconds: 3,
  defaults: {
    keywords: [],
    city: "",
    salary_min: null,
    experience: "",
    education: "",
    filters: {},
    job_type: "",
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
  // 站点健康度：本文件不测 degraded 标记，给一份"无告警"的空列表即可（当前站点会被判为 ok）。
  apiMocks.getSiteHealth.mockResolvedValue({ sites: [] });
  apiMocks.getCollectFilterOptions.mockResolvedValue({ groups: [] });
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

  it("returns to the console mid-collection and still shows the collect progress", async () => {
    // 用户开始采集后切走，再回到投递台——这条路径背后是后端 `/tasks/current`。
    // 它曾经写死只认投递批次，于是采集批次在界面上"不存在"：进度面板空着，暂停按钮也没有。
    apiMocks.getCurrentTask.mockResolvedValue({
      ...runningTask(),
      kind: "collect",
      total: 30,
      processed: 12,
      succeeded: 12,
    });
    apiMocks.getCollectTaskDetail.mockResolvedValue(
      detail({ kind: "collect", total: 30, processed: 12, succeeded: 12 }),
    );

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    expect(await screen.findByText("采集批次", {}, { timeout: 20_000 })).toBeInTheDocument();
    expect(screen.getByText(/已处理/)).toBeInTheDocument();
    // 采集跑到一半也必须能暂停——用户可能刚发现关键词写错了。
    expect(screen.getByRole("button", { name: /暂停/ })).toBeEnabled();
    expect(apiMocks.getCollectTaskDetail).toHaveBeenCalledWith(7);
  });

  it("pauses and resumes a running collect batch from the console", async () => {
    apiMocks.getCurrentTask.mockResolvedValue({ ...runningTask(), kind: "collect" });
    apiMocks.getCollectTaskDetail.mockResolvedValue(detail({ kind: "collect" }));
    apiMocks.pauseTask.mockResolvedValue({ ...runningTask(), kind: "collect", status: "paused" });

    render(
      <AntdApp>
        <ApplyPage />
      </AntdApp>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /暂停/ }, { timeout: 20_000 }));

    await waitFor(() => expect(apiMocks.pauseTask).toHaveBeenCalledWith(7));
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
    // 用 getByText 会命中多个元素；而且页面上现在还有一条「采集之后还有两步」的流程提示，
    // 同 role=alert，所以按**类名**定位这一条，而不是按 role。
    await screen.findByText("以下条件未生效");
    const banner = document.querySelector(".apply-collect-unmapped");
    expect(banner).toHaveTextContent("以下条件未生效");
    expect(banner).toHaveTextContent("薪资");
    expect(banner).toHaveTextContent("学历");
  });

  it("reports the local filter outcome, including conditions it could not apply", async () => {
    // 本地筛选的三件事都要说出来：筛掉几条、几条因为岗位没写字段而没能判断、
    // 以及用户自己填的条件有没有被识别。少说一件，用户就不知道"少了几个"是怎么少的。
    const collectTask = detail({
      kind: "collect",
      config: {
        filter_applied: ["薪资", "经验", "学历"],
        filtered_out: 2,
        filter_reasons: ["学历"],
        filter_undecided: ["经验"],
        filter_undecided_count: 3,
        filter_unapplied: ["学历"],
      },
    });

    render(
      <AntdApp>
        <CollectPanel disabled={false} onStarted={vi.fn()} collectTask={collectTask} />
      </AntdApp>,
    );

    expect(await screen.findByText(/已按薪资 \/ 经验 \/ 学历在采集后筛选/)).toBeInTheDocument();
    expect(screen.getByText(/本次筛掉 2 个不符合条件的岗位/)).toBeInTheDocument();
    expect(screen.getByText(/3 个岗位没有写经验/)).toBeInTheDocument();
    expect(screen.getByText(/这条条件没能识别，本次没有生效/)).toBeInTheDocument();
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

  it("keeps site-sample saving off by default and only sends true when ticked", async () => {
    // 保存站点原文是"往磁盘写站点数据"的动作，默认必须关闭；勾了才把 true 传给后端。
    apiMocks.getCollectConfig.mockResolvedValue({ ...COLLECT_CONFIG, keywords: ["后端"] });
    apiMocks.updateCollectConfig.mockResolvedValue({ ...COLLECT_CONFIG, keywords: ["后端"] });
    apiMocks.createCollectTask.mockResolvedValue(detail({ kind: "collect" }));

    render(
      <AntdApp>
        <CollectPanel disabled={false} onStarted={vi.fn()} collectTask={null} />
      </AntdApp>,
    );

    // 说明文案必须存在：用户得知道"存什么、存哪、会不会外传"。
    expect(await screen.findByText(/只存到本机 backend\/data\/captures\//)).toBeInTheDocument();
    // 等表单填上关键词，否则点「开始采集」会因为"没填关键词或城市"直接返回、根本不发请求。
    await screen.findByText("后端");

    // aria-label 是给这里定位用的：antd 会给两字中文按钮自动插空格，用中文文本当查询条件会找不到。
    const box = screen.getByLabelText(
      "保存本次抓到的站点原文（用于排查解析问题）",
    ) as HTMLInputElement;
    expect(box.checked).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /开始采集/ }));
    await waitFor(() => expect(apiMocks.createCollectTask).toHaveBeenCalledWith(false));

    apiMocks.createCollectTask.mockClear();
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: /开始采集/ }));
    await waitFor(() => expect(apiMocks.createCollectTask).toHaveBeenCalledWith(true));
  });
});
