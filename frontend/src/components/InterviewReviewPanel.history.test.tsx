/** 复盘面板：分析后自动保存、历史记录富还原（反向优化简历可点并写回）、旧版纯文本兼容。 */
import { App as AntApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import InterviewReviewPanel from "./InterviewReviewPanel";

const apiMocks = vi.hoisted(() => ({
  analyzeInterviewQuestion: vi.fn(),
  optimizeResumeFromInterview: vi.fn(),
  listReviews: vi.fn(),
  saveReview: vi.fn(),
  updateReview: vi.fn(),
  deleteReview: vi.fn(),
}));

vi.mock("../api/interview", () => apiMocks);

const ANALYSIS = {
  question: "这个项目难点怎么解决？",
  framework: "先讲背景，再讲取舍与结果。",
  key_points: ["说明约束"],
  follow_up: ["这个指标怎么算的"],
  pitfalls: ["只讲过程不讲结果"],
};

const OPTIMIZE = {
  resume_id: 1,
  llm_used: true,
  notes: [],
  suggestions: [
    {
      priority: "high",
      section: "项目经历",
      issue: "难点描述不够量化",
      suggestion: "补充指标与对比",
      evidence: ["面试被追问指标口径"],
    },
  ],
};

const RECORD = {
  id: 9,
  job_id: null,
  job_title: "",
  company: "",
  resume_id: null,
  resume_title: "",
  questions: ["这个项目难点怎么解决？"],
  analysis: ANALYSIS,
  suggestions: [],
  model: "",
  created_at: "2026-09-20T10:00:00",
  updated_at: "2026-09-20T10:00:00",
};

function renderPanel(props: Partial<React.ComponentProps<typeof InterviewReviewPanel>> = {}) {
  return render(
    <AntApp>
      <InterviewReviewPanel
        jobOptions={[{ value: 1, label: "后端开发工程师" }]}
        resumeOptions={[{ value: 1, label: "我的简历" }]}
        onGoToResume={() => {}}
        {...props}
      />
    </AntApp>,
  );
}

beforeEach(() => {
  apiMocks.analyzeInterviewQuestion.mockReset().mockResolvedValue(ANALYSIS);
  apiMocks.optimizeResumeFromInterview.mockReset().mockResolvedValue(OPTIMIZE);
  apiMocks.listReviews.mockReset().mockResolvedValue([]);
  apiMocks.saveReview.mockReset().mockResolvedValue(undefined);
  apiMocks.updateReview.mockReset().mockResolvedValue(undefined);
  apiMocks.deleteReview.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("InterviewReviewPanel 自动保存与历史富还原", () => {
  it("分析出思路后自动保存被调用", async () => {
    renderPanel();

    fireEvent.change(screen.getByPlaceholderText(/录入面试里真实被问的问题/), {
      target: { value: "这个项目难点怎么解决？" },
    });
    fireEvent.click(screen.getByRole("button", { name: /分析答题思路/ }));

    await waitFor(() => expect(apiMocks.saveReview).toHaveBeenCalled());
    expect(apiMocks.saveReview).toHaveBeenCalledWith(
      expect.objectContaining({ questions: ["这个项目难点怎么解决？"], analysis: ANALYSIS }),
    );
  });

  it("点击历史「查看详情」把记录交给父组件打开", async () => {
    apiMocks.listReviews.mockResolvedValue([RECORD]);
    const onOpenRecord = vi.fn();
    renderPanel({ onOpenRecord });

    expect(await screen.findByText("复盘")).toBeInTheDocument();
    fireEvent.click(screen.getByText("复盘"));
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));

    await waitFor(() => expect(onOpenRecord).toHaveBeenCalledWith(RECORD));
  });

  it("历史记录富还原：反向优化简历按钮可点并写回该条记录", async () => {
    renderPanel({ record: RECORD });

    // 历史记录的答题思路已直接渲染（与生成时相同路径）。
    expect(await screen.findByText(/先讲背景/)).toBeInTheDocument();

    // 选简历后点击「反向优化简历」。
    const resumeSelect = screen
      .getByText("关联简历（反向优化必选）")
      .closest(".ant-select-selector");
    fireEvent.mouseDown(resumeSelect!);
    fireEvent.click(await screen.findByText("我的简历"));

    fireEvent.click(screen.getByRole("button", { name: /反向优化简历/ }));

    expect(await screen.findByText(/补充指标与对比/)).toBeInTheDocument();
    expect(apiMocks.optimizeResumeFromInterview).toHaveBeenCalledWith({
      resume_id: 1,
      job_id: null,
      weaknesses: ANALYSIS.pitfalls,
      follow_ups: ANALYSIS.follow_up,
    });

    // 生成结果写回同一条历史记录（PATCH）。
    await waitFor(() =>
      expect(apiMocks.updateReview).toHaveBeenCalledWith(
        9,
        expect.objectContaining({
          analysis: ANALYSIS,
          suggestions: OPTIMIZE.suggestions,
        }),
      ),
    );
  });

  it("旧版纯文本记录仅兼容展示并提示仅可查看", async () => {
    renderPanel({
      record: { ...RECORD, analysis: "旧版纯文本复盘内容……" } as unknown as typeof RECORD,
    });

    expect(await screen.findByText("此为旧版记录，仅可查看")).toBeInTheDocument();
    expect(screen.getByText(/旧版纯文本复盘内容/)).toBeInTheDocument();
  });
});
