/** 简历风险扫描面板：风险点渲染、台账联动、错误透出。 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ResumeRiskPanel from "./ResumeRiskPanel";

const apiMocks = vi.hoisted(() => ({ scanResumeRisks: vi.fn() }));

vi.mock("../api/resumeRisk", () => apiMocks);

const RESULT = {
  resume_id: 7,
  points: [
    {
      category: "deep_dive",
      severity: "high",
      text: "主导交易系统从0到1建设",
      location: "事实台账「主导交易系统」",
      suggestion: "这条强主张会被追问，建议准备边界与依据",
      claim_id: 42,
      follow_up: ["个人边界：团队负责整体架构，我负责撮合引擎"],
    },
    {
      category: "compliance",
      severity: "high",
      text: "保密协议",
      location: "正文",
      suggestion: "可能涉及保密信息，投递前请确认",
      claim_id: null,
      follow_up: [],
    },
  ],
  summary: { deep_dive: 1, compliance: 1 },
  llm_used: false,
  notes: [],
};

beforeEach(() => {
  apiMocks.scanResumeRisks.mockReset();
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ResumeRiskPanel", () => {
  it("渲染风险点、五类分组与台账联动", async () => {
    apiMocks.scanResumeRisks.mockResolvedValue(RESULT);
    render(<ResumeRiskPanel resumeId={7} />);

    expect(await screen.findByText("共 2 条风险点")).toBeInTheDocument();
    expect(screen.getByText("深挖风险点")).toBeInTheDocument();
    expect(screen.getByText("合规校验")).toBeInTheDocument();
    expect(screen.getByText("主导交易系统从0到1建设")).toBeInTheDocument();
    expect(screen.getByText("台账 #42")).toBeInTheDocument();
    expect(screen.getByText(/这条强主张会被追问/)).toBeInTheDocument();
    expect(apiMocks.scanResumeRisks).toHaveBeenCalledWith(7);
  });

  it("接口报错时透出中文错误", async () => {
    apiMocks.scanResumeRisks.mockRejectedValue(new Error("风险扫描失败"));
    render(<ResumeRiskPanel resumeId={7} />);

    expect(await screen.findByText("风险扫描失败")).toBeInTheDocument();
  });
});
