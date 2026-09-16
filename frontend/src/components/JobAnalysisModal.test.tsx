import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, JobAnalysisResult } from "../types";
import JobAnalysisModal from "./JobAnalysisModal";

const apiMocks = vi.hoisted(() => ({ generateJobAnalysis: vi.fn() }));

vi.mock("../api/jobs", () => ({ generateJobAnalysis: apiMocks.generateJobAnalysis }));

const JOB: Job = {
  id: 12,
  title: "护士",
  company: "示例医院",
  location: "杭州",
  salary: "",
  job_type: "社招",
  description: "负责病区护理工作。",
  requirements: "持有护士执业资格证。",
  additional_info: "提供岗位培训。",
  keywords: [],
  source: "手动添加",
  source_url: "",
  posted_at: "2026年8月20日",
  status: "开放中",
  note: "",
  note_images: [],
  recognition_source: "",
  favorite: false,
  created_at: "2026-08-20T09:00:00",
  updated_at: "2026-08-20T09:00:00",
};

const ANALYSIS: JobAnalysisResult = {
  summary: "岗位重点是病区护理与执业资格。",
  requirements: [
    {
      priority: "high",
      category: "职业资质",
      requirement: "持有护士执业资格证",
      evidence: "持有护士执业资格证。",
    },
  ],
  advice: [
    {
      title: "突出临床能力",
      action: "在简历中说明病区实习和护理操作经验。",
      rationale: "岗位职责直接涉及病区护理。",
    },
  ],
};

beforeEach(() => {
  apiMocks.generateJobAnalysis.mockReset().mockResolvedValue(ANALYSIS);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("JobAnalysisModal", () => {
  it("generates and renders the selected job analysis when opened", async () => {
    render(<JobAnalysisModal job={JOB} onClose={vi.fn()} />);

    expect(apiMocks.generateJobAnalysis).toHaveBeenCalledWith(JOB.id);
    expect(await screen.findByText(ANALYSIS.summary)).toBeInTheDocument();
    expect(screen.getByText("核心要求")).toBeInTheDocument();
    expect(screen.getByText("持有护士执业资格证")).toBeInTheDocument();
    expect(screen.getByText("突出临床能力")).toBeInTheDocument();
  });

  it("shows a friendly error and lets the user retry", async () => {
    apiMocks.generateJobAnalysis
      .mockRejectedValueOnce(new Error("模型暂时不可用"))
      .mockResolvedValueOnce(ANALYSIS);

    render(<JobAnalysisModal job={JOB} onClose={vi.fn()} />);

    expect(await screen.findByText("模型暂时不可用")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新生成解读" }));

    expect(await screen.findByText(ANALYSIS.summary)).toBeInTheDocument();
    expect(apiMocks.generateJobAnalysis).toHaveBeenCalledTimes(2);
  });

  it("regenerates an existing analysis only after the user asks", async () => {
    const updated = { ...ANALYSIS, summary: "第二次生成的岗位总结。" };
    apiMocks.generateJobAnalysis.mockResolvedValueOnce(ANALYSIS).mockResolvedValueOnce(updated);

    render(<JobAnalysisModal job={JOB} onClose={vi.fn()} />);

    expect(await screen.findByText(ANALYSIS.summary)).toBeInTheDocument();
    expect(apiMocks.generateJobAnalysis).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "重新生成" }));

    expect(await screen.findByText(updated.summary)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(ANALYSIS.summary)).not.toBeInTheDocument());
    expect(apiMocks.generateJobAnalysis).toHaveBeenCalledTimes(2);
  });
});
