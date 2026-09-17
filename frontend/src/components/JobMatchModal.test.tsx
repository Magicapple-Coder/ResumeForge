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

  it("renders the five-way taxonomy, admission and hard gate without any percentage", async () => {
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
    // 设计硬约束：绝不渲染任何百分比 / 评分。
    expect(document.body.textContent ?? "").not.toContain("%");
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
