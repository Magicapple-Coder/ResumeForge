/** 个性化题库面板：无选择校验、三类分组渲染、开始模拟面试回传题目。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QuestionBankPanel from "./QuestionBankPanel";

const apiMocks = vi.hoisted(() => ({
  generateQuestionBank: vi.fn(),
  generateQuestionAnswer: vi.fn(),
  listQuestionBanks: vi.fn(),
  saveQuestionBank: vi.fn(),
  deleteQuestionBank: vi.fn(),
}));

vi.mock("../api/interview", () => apiMocks);

const RESULT = {
  job_id: 1,
  job_title: "后端开发工程师",
  company: "示例公司",
  resume_id: null,
  llm_used: true,
  notes: [],
  groups: [
    {
      type: "基础题",
      questions: [
        { question: "请自我介绍", purpose: "考察表达", answer_hint: "按 STAR 展开" },
      ],
    },
    {
      type: "项目深挖题",
      questions: [
        { question: "交易系统难点", purpose: "考察取舍", answer_hint: "说清个人边界" },
      ],
    },
    {
      type: "反问HR题",
      questions: [
        { question: "团队如何协作", purpose: "了解团队", answer_hint: "问成长路径" },
      ],
    },
  ],
};

async function pickJob(optionText: string) {
  const placeholder = screen.getByText("关联岗位（选填）");
  const selector = placeholder.closest(".ant-select-selector");
  fireEvent.mouseDown(selector!);
  fireEvent.click(await screen.findByText(optionText));
}

function renderPanel(props: React.ComponentProps<typeof QuestionBankPanel>) {
  return render(
    <AntdApp>
      <QuestionBankPanel {...props} />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.generateQuestionBank.mockReset();
  apiMocks.generateQuestionAnswer.mockReset();
  apiMocks.listQuestionBanks.mockReset().mockResolvedValue([]);
  apiMocks.saveQuestionBank.mockReset();
  apiMocks.deleteQuestionBank.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("QuestionBankPanel", () => {
  it("未选择岗位或简历时给出提示且不请求", async () => {
    renderPanel({ jobOptions: [], resumeOptions: [] });
    fireEvent.click(screen.getByRole("button", { name: /生成题库/ }));

    expect(await screen.findByText(/请至少选择一个岗位或一份简历/)).toBeInTheDocument();
    expect(apiMocks.generateQuestionBank).not.toHaveBeenCalled();
  });

  it("生成后按三类分组渲染并可回传题目开始模拟面试", async () => {
    apiMocks.generateQuestionBank.mockResolvedValue(RESULT);
    const onStartSession = vi.fn();
    renderPanel({
      jobOptions: [{ value: 1, label: "后端开发工程师" }],
      resumeOptions: [],
      onStartSession,
    });

    await pickJob("后端开发工程师");
    fireEvent.click(screen.getByRole("button", { name: /生成题库/ }));

    expect(await screen.findByText("共 3 题")).toBeInTheDocument();
    expect(screen.getByText("基础题")).toBeInTheDocument();
    expect(screen.getByText("项目深挖题")).toBeInTheDocument();
    expect(screen.getByText("反问HR题")).toBeInTheDocument();
    expect(screen.getByText(/请自我介绍/)).toBeInTheDocument();
    expect(apiMocks.generateQuestionBank).toHaveBeenCalledWith({ job_id: 1, resume_id: null });

    fireEvent.click(screen.getByRole("button", { name: /开始模拟面试/ }));
    expect(onStartSession).toHaveBeenCalledWith([
      "请自我介绍",
      "交易系统难点",
      "团队如何协作",
    ]);
  });

  it("接口报错时透出中文错误", async () => {
    apiMocks.generateQuestionBank.mockRejectedValue(new Error("生成题库失败：模型超时"));
    renderPanel({
      jobOptions: [{ value: 1, label: "后端开发工程师" }],
      resumeOptions: [],
    });

    await pickJob("后端开发工程师");
    fireEvent.click(screen.getByRole("button", { name: /生成题库/ }));

    expect(await screen.findByText("生成题库失败：模型超时")).toBeInTheDocument();
  });

  it("点「参考答案」展开详细答案与话术，再点收起", async () => {
    apiMocks.generateQuestionBank.mockResolvedValue(RESULT);
    apiMocks.generateQuestionAnswer.mockResolvedValue({
      question: "请自我介绍",
      answer: "围绕过往经历，用 STAR 结构讲清背景、任务、行动与结果。",
      key_points: ["先说结论", "量化结果"],
      sample_phrasing: "我在上一份工作里负责……，最终将耗时缩短了 30%。",
    });
    renderPanel({
      jobOptions: [{ value: 1, label: "后端开发工程师" }],
      resumeOptions: [],
    });

    await pickJob("后端开发工程师");
    fireEvent.click(screen.getByRole("button", { name: /生成题库/ }));
    await screen.findByText("共 3 题");

    const answerButtons = screen.getAllByRole("button", { name: /参考答案/ });
    fireEvent.click(answerButtons[0]);

    expect(await screen.findByText(/围绕过往经历/)).toBeInTheDocument();
    expect(screen.getByText("先说结论")).toBeInTheDocument();
    expect(screen.getByText("量化结果")).toBeInTheDocument();
    expect(screen.getByText(/话术参考：我在上一份工作里负责/)).toBeInTheDocument();
    expect(apiMocks.generateQuestionAnswer).toHaveBeenCalledWith({
      question: "请自我介绍",
      job_id: 1,
      resume_id: null,
    });

    fireEvent.click(screen.getByRole("button", { name: /收起参考答案/ }));
    await waitFor(() => expect(screen.queryByText(/围绕过往经历/)).not.toBeInTheDocument());
  });

  it("生成后「保存题库」把分组与快照落成历史", async () => {
    apiMocks.generateQuestionBank.mockResolvedValue(RESULT);
    apiMocks.saveQuestionBank.mockResolvedValue({
      id: 1,
      job_id: 1,
      job_title: "后端开发工程师",
      company: "示例公司",
      resume_id: null,
      resume_title: "",
      groups: RESULT.groups,
      model: "",
      created_at: "2026-09-20T10:00:00",
      updated_at: "2026-09-20T10:00:00",
    });
    renderPanel({
      jobOptions: [{ value: 1, label: "后端开发工程师" }],
      resumeOptions: [],
    });

    await pickJob("后端开发工程师");
    fireEvent.click(screen.getByRole("button", { name: /生成题库/ }));
    await screen.findByText("共 3 题");

    fireEvent.click(screen.getByRole("button", { name: /保存题库/ }));

    await waitFor(() =>
      expect(apiMocks.saveQuestionBank).toHaveBeenCalledWith({
        job_id: 1,
        job_title: "后端开发工程师",
        company: "示例公司",
        resume_id: null,
        resume_title: "",
        groups: RESULT.groups,
        model: "",
      }),
    );
  });

  it("「历史题库」回看某次生成的分组并可删除", async () => {
    apiMocks.listQuestionBanks.mockResolvedValue([
      {
        id: 1,
        job_id: 1,
        job_title: "后端开发工程师",
        company: "示例公司",
        resume_id: null,
        resume_title: "",
        groups: RESULT.groups,
        model: "",
        created_at: "2026-09-20T10:00:00",
        updated_at: "2026-09-20T10:00:00",
      },
    ]);
    renderPanel({ jobOptions: [], resumeOptions: [] });

    expect(await screen.findByText("后端开发工程师")).toBeInTheDocument();

    // 展开历史条目，回看分组里的题目。
    fireEvent.click(screen.getByText("后端开发工程师"));
    expect(await screen.findByText("请自我介绍")).toBeInTheDocument();

    // 删除需二次确认，确认后走删除接口。
    fireEvent.click(screen.getByRole("button", { name: /删除/ }));
    fireEvent.click(await screen.findByRole("button", { name: "确认删除题库历史 1" }));

    await waitFor(() => expect(apiMocks.deleteQuestionBank).toHaveBeenCalledWith(1));
  });
});
