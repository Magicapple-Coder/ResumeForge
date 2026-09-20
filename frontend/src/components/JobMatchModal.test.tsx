import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, JobMatchOut } from "../types";
import JobMatchModal from "./JobMatchModal";

const apiMocks = vi.hoisted(() => ({
  getJobMatch: vi.fn(),
  generateJobMatch: vi.fn(),
  deleteJobMatch: vi.fn(),
}));

vi.mock("../api/jobs", () => ({
  getJobMatch: apiMocks.getJobMatch,
  generateJobMatch: apiMocks.generateJobMatch,
  deleteJobMatch: apiMocks.deleteJobMatch,
}));

const JOB: Job = {
  id: 12,
  title: "后端开发",
  company: "示例科技",
  location: "北京",
  salary: "20-30K",
  job_type: "社招",
  description: "负责后端服务开发。",
  requirements: "熟悉 Python；本科及以上学历。",
  additional_info: "",
  keywords: [],
  source: "BOSS直聘",
  source_url: "https://www.zhipin.com/job/12",
  posted_at: "",
  status: "开放中",
  note: "",
  note_images: [],
  recognition_source: "岗位采集",
  favorite: false,
  created_at: "2026-09-17T08:00:00",
  updated_at: "2026-09-17T08:00:00",
};

const ANALYZED: JobMatchOut = {
  id: 5,
  job_id: 12,
  job_title: "后端开发",
  company: "示例科技",
  result: {
    hard_conditions: [
      {
        label: "本科及以上",
        jd_quote: "本科及以上学历",
        status: "matched",
        evidence: "本科",
      },
      {
        label: "硕士及以上",
        jd_quote: "本科及以上学历",
        status: "real_gap",
        evidence: "资料中未提供",
      },
    ],
    core_abilities: [
      {
        label: "熟悉 Python",
        jd_quote: "熟悉 Python",
        status: "expression_gap",
        evidence: "Python 出现在技能表",
      },
    ],
    bonus_items: [
      {
        label: "有开源经历",
        jd_quote: "",
        status: "evidence_insufficient",
        evidence: "资料中未提供",
      },
    ],
    hard_gate: "unmet",
    admission: "block",
    advice: "该岗位存在真实缺口，建议先补足后再投。",
    notes: ["团队成果不计入个人能力。"],
  },
  hard_gate: "unmet",
  requires_confirm: true,
  model: "demo-model",
  created_at: "2026-09-17T08:00:00",
  updated_at: "2026-09-17T08:00:00",
  reference_score: {
    score: 62,
    dimensions: [
      { key: "skills", label: "技能覆盖", score: 75, weight: 0.3, evidence: "命中 3/4 个关键词" },
      { key: "seniority", label: "年限", score: 50, weight: 0.2, evidence: "" },
    ],
    disclaimer:
      "本参考分由本地规则估算，仅供展示与自我评估，不代表真实 ATS 解析结果或投递成功概率；投递准入仍以五类匹配结论为准。",
  },
};

const NOT_ANALYZED: JobMatchOut = {
  id: 0,
  job_id: 12,
  job_title: "后端开发",
  company: "示例科技",
  result: {
    hard_conditions: [],
    core_abilities: [],
    bonus_items: [],
    hard_gate: "unknown",
    admission: "needs_confirm",
    advice: "",
    notes: [],
  },
  hard_gate: "unknown",
  requires_confirm: false,
  model: "",
  created_at: "2026-09-17T08:00:00",
  updated_at: "2026-09-17T08:00:00",
  reference_score: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getJobMatch.mockResolvedValue(NOT_ANALYZED);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("JobMatchModal", () => {
  it("offers to start an analysis when the job has none yet", async () => {
    render(
      <AntdApp>
        <JobMatchModal job={JOB} onClose={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("这个岗位还没有做过匹配分析")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /开始分析/ })).toBeInTheDocument();
  });

  it("renders the five-way taxonomy, admission and hard gate as plain states", async () => {
    apiMocks.getJobMatch.mockResolvedValue(ANALYZED);

    render(
      <AntdApp>
        <JobMatchModal job={JOB} onClose={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("已匹配")).toBeInTheDocument();
    expect(screen.getByText("表达缺口")).toBeInTheDocument();
    expect(screen.getByText("证据不足")).toBeInTheDocument();
    expect(screen.getByText("真实缺口")).toBeInTheDocument();
    expect(screen.getByText("不投")).toBeInTheDocument();
    expect(screen.getByText("硬性条件未满足")).toBeInTheDocument();
    // **五类结论**是不带评分的：整套结论区里不能出现百分比 / 百分号。
    // （「匹配度参考分」是另一个区块、且强制带免责，它的分数是 0–100 的整数、同样不写成 %。）
    expect(document.body.textContent ?? "").not.toContain("%");
  });

  it("渲染匹配度参考分：总分 + 分项 + 后端下发的免责文案", async () => {
    apiMocks.getJobMatch.mockResolvedValue(ANALYZED);

    render(
      <AntdApp>
        <JobMatchModal job={JOB} onClose={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("匹配度参考分")).toBeInTheDocument();
    expect(screen.getByText("技能覆盖")).toBeInTheDocument();
    expect(screen.getByText("命中 3/4 个关键词")).toBeInTheDocument();
    // 免责文案来自后端，必须原样展示——这是"参考分不能被当成结论"的唯一保底。
    expect(
      screen.getByText(/仅供展示与自我评估，不代表真实 ATS 解析结果或投递成功概率/),
    ).toBeInTheDocument();
  });

  it("没有参考分时不渲染该区块", async () => {
    apiMocks.getJobMatch.mockResolvedValue({ ...ANALYZED, reference_score: null });

    render(
      <AntdApp>
        <JobMatchModal job={JOB} onClose={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("已匹配")).toBeInTheDocument();
    expect(screen.queryByText("匹配度参考分")).toBeNull();
  });

  it("forces a re-analysis only when the user asks", async () => {
    apiMocks.getJobMatch.mockResolvedValue(ANALYZED);
    apiMocks.generateJobMatch.mockResolvedValue(ANALYZED.result);

    render(
      <AntdApp>
        <JobMatchModal job={JOB} onClose={vi.fn()} />
      </AntdApp>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /重新分析/ }));

    await waitFor(() => expect(apiMocks.generateJobMatch).toHaveBeenCalledWith(JOB.id, true));
  });

  it("shows a friendly error with a retry action", async () => {
    apiMocks.getJobMatch.mockRejectedValue(new Error("资料为空，请先完善个人资料"));

    render(
      <AntdApp>
        <JobMatchModal job={JOB} onClose={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("资料为空，请先完善个人资料")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
  });
});
