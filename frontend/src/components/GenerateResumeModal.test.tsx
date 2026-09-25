/** 生成弹窗在「没有岗位」（通用简历）时的行为，以及后台生成任务的前端交互。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TEMPLATE_CATALOG } from "../test/resumeFixtures";
import type { ResumeContent, ResumeDetail, ResumeGenerateTask } from "../types";
import { resetBackgroundTasks } from "../utils/backgroundTasks";
import { registerNotifyHost } from "../utils/taskNotify";
import GenerateResumeModal from "./GenerateResumeModal";

/** 记录"完成提醒"的假宿主：真实呈现由 AntD 负责，组件测试只关心有没有提醒、什么形式。 */
const notices: { title: string; modal?: boolean; confirmLabel?: string }[] = [];

const fakeNotifyHost = {
  notification: {
    success: (config: { message: unknown }) =>
      notices.push({ title: String(config.message), modal: false }),
    warning: (config: { message: unknown }) =>
      notices.push({ title: String(config.message), modal: false }),
    error: (config: { message: unknown }) =>
      notices.push({ title: String(config.message), modal: false }),
    info: (config: { message: unknown }) =>
      notices.push({ title: String(config.message), modal: false }),
  },
  modal: {
    info: (config: { message: unknown; okText?: unknown }) =>
      notices.push({
        title: String(config.message),
        modal: true,
        confirmLabel: config.okText ? String(config.okText) : undefined,
      }),
  },
};

const apiMocks = vi.hoisted(() => ({
  startResumeGeneration: vi.fn(),
  getResumeGenerateTask: vi.fn(),
  cancelResumeGenerateTask: vi.fn(),
  getResume: vi.fn(),
  renderResume: vi.fn(),
  updateResume: vi.fn(),
  updateResumeLayout: vi.fn(),
  fetchResumeTemplates: vi.fn(),
  getLLMConfig: vi.fn(),
}));

// 展开真实模块再覆盖：显式列导出的话，生产代码新增一个导出就会让这里的
// 调用直接抛"export is not defined"，看起来像组件挂了。
vi.mock("../api/resumes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/resumes")>()),
  startResumeGeneration: apiMocks.startResumeGeneration,
  getResumeGenerateTask: apiMocks.getResumeGenerateTask,
  cancelResumeGenerateTask: apiMocks.cancelResumeGenerateTask,
  getResume: apiMocks.getResume,
  renderResume: apiMocks.renderResume,
  updateResume: apiMocks.updateResume,
  updateResumeLayout: apiMocks.updateResumeLayout,
  fetchResumeTemplates: apiMocks.fetchResumeTemplates,
}));
vi.mock("../api/settings", () => ({ getLLMConfig: apiMocks.getLLMConfig }));

/** 一个正在运行的后台生成任务。用函数造值，让每个用例都能按需覆盖字段。 */
function makeTask(overrides: Partial<ResumeGenerateTask> = {}): ResumeGenerateTask {
  return {
    id: 1,
    status: "running",
    resume_id: null,
    error: "",
    message: "",
    received_chars: 0,
    job_id: null,
    title: "",
    created_at: "2025-01-01T00:00:00",
    started_at: "2025-01-01T00:00:00",
    finished_at: null,
    ...overrides,
  };
}

const EMPTY_CONTENT: ResumeContent = {
  photo: "",
  name: "",
  gender: "",
  birth_year: "",
  phone: "",
  email: "",
  city: "",
  job_intent: "",
  summary: "",
  education: [],
  experience: [],
  campus_experience: [],
  projects: [],
  skills: [],
  awards: [],
};

const RESUME_DETAIL: ResumeDetail = {
  id: 7,
  title: "张三-通用简历-20250101",
  job_id: null,
  job_title: "",
  company: "",
  source: "ai",
  favorite: false,
  note: "",
  model: "m",
  enhancement_enabled: false,
  enhancement_level: "balanced",
  template: "classic",
  format_name: "",
  format_config: {},
  page_limit: 1,
  font_scale: "standard",
  created_at: "2025-01-01T00:00:00",
  content: EMPTY_CONTENT,
  warnings: [],
  parse_error: "",
};

beforeEach(() => {
  notices.length = 0;
  // 登记表是模块级单例：不清的话，上一个用例留下的任务会被继续轮询。
  resetBackgroundTasks();
  registerNotifyHost(fakeNotifyHost as never);
  apiMocks.startResumeGeneration.mockReset();
  apiMocks.getResumeGenerateTask.mockReset();
  apiMocks.cancelResumeGenerateTask.mockReset();
  apiMocks.getResume.mockReset();
  apiMocks.renderResume.mockReset();
  apiMocks.updateResume.mockReset();
  apiMocks.updateResumeLayout.mockReset();
  apiMocks.fetchResumeTemplates.mockReset();
  apiMocks.getLLMConfig.mockReset();
  apiMocks.getLLMConfig.mockResolvedValue({ base_url: "https://api.example.com/v1", model: "m" });
  apiMocks.startResumeGeneration.mockResolvedValue(makeTask());
  // 默认轮询返回"仍在运行"，避免无关用例误入终态分支。
  apiMocks.getResumeGenerateTask.mockResolvedValue(makeTask());
  apiMocks.fetchResumeTemplates.mockResolvedValue(TEMPLATE_CATALOG);
});

afterEach(() => {
  // 登记表是模块级单例，且它自己带一个 setInterval：不清空的话定时器会一直挂着，
  // 整个测试进程结束不了（实测卡了十几分钟）。
  resetBackgroundTasks();
  cleanup();
  document.body.innerHTML = "";
});

function renderModal(props: Partial<React.ComponentProps<typeof GenerateResumeModal>> = {}) {
  return render(
    <MemoryRouter>
      <AntdApp>
        <GenerateResumeModal job={null} open onClose={vi.fn()} {...props} />
      </AntdApp>
    </MemoryRouter>,
  );
}

describe("GenerateResumeModal 通用简历", () => {
  it("offers a name field and drops the job-oriented copy", async () => {
    renderModal();

    expect(await screen.findByText("生成通用简历")).toBeInTheDocument();
    expect(screen.getByLabelText("简历名称")).toBeInTheDocument();
    // 没有岗位就不该出现岗位口径的文案与入口
    expect(screen.queryByText(/根据岗位要求美化拓展经历/)).not.toBeInTheDocument();
    expect(screen.queryByText(/查看对应岗位/)).not.toBeInTheDocument();
    expect(screen.getByText(/通用简历不针对任何岗位/)).toBeInTheDocument();
  });

  it("submits with a null job_id and the typed name", async () => {
    renderModal({ initialTitle: "研发通用版" });

    const nameInput = await screen.findByLabelText("简历名称");
    expect(nameInput).toHaveValue("研发通用版");
    fireEvent.click(screen.getByRole("button", { name: /开始生成/ }));

    await waitFor(() => expect(apiMocks.startResumeGeneration).toHaveBeenCalledOnce());
    expect(apiMocks.startResumeGeneration.mock.calls[0][0]).toMatchObject({
      job_id: null,
      title: "研发通用版",
    });
  });

  it("sends an empty title when the user leaves the name blank", async () => {
    renderModal();

    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    await waitFor(() => expect(apiMocks.startResumeGeneration).toHaveBeenCalledOnce());
    // 留空交给后端按「姓名-通用简历-时间」命名
    expect(apiMocks.startResumeGeneration.mock.calls[0][0].title).toBe("");
  });
});

/** 当前被选中的分段控件标签（antd 把选中态放在 .ant-segmented-item-selected 上）。 */
function selectedSegments(): string[] {
  return Array.from(
    document.querySelectorAll(".ant-segmented-item-selected .ant-segmented-item-label"),
  ).map((node) => node.textContent ?? "");
}

describe("GenerateResumeModal 版式默认值", () => {
  it("resets the page limit on every open, not just the first", async () => {
    // 必须复用**同一个实例**：弹窗是常驻组件、靠 open 开关，父组件不会把它卸载重建。
    // 换成卸载后重新 render，新实例的 useState 初值本来就是 1，测出来的永远是绿的。
    const view = renderModal({ open: true });
    await waitFor(() => expect(apiMocks.fetchResumeTemplates).toHaveBeenCalled());

    // 版式控件在拿到模型配置之前是禁用的，先等它可用再点。
    await waitFor(() => expect(screen.getByRole("radio", { name: "3 页" })).toBeEnabled());
    // 点可见的标签而不是那个隐藏的 input：antd 把点击处理挂在标签上，
    // 直接点 input 不会触发 onChange（值不变，断言就会看到"未选中"）。
    fireEvent.click(screen.getByText("3 页"));
    expect(selectedSegments()).toContain("3 页");

    view.rerender(
      <MemoryRouter>
        <AntdApp>
          <GenerateResumeModal job={null} open={false} onClose={vi.fn()} />
        </AntdApp>
      </MemoryRouter>,
    );
    view.rerender(
      <MemoryRouter>
        <AntdApp>
          <GenerateResumeModal job={null} open onClose={vi.fn()} />
        </AntdApp>
      </MemoryRouter>,
    );

    // 此前只重置了模板和字号，页数会沿用上一次的选择，与"默认一页 A4"相矛盾。
    await waitFor(() => expect(selectedSegments()).toContain("1 页"));
    expect(selectedSegments()).not.toContain("3 页");
  });
});

/** 当前阶段条里被标成 active 的步骤标题（antd Steps 的选中态类名）。 */
function activeStepTitle(): string | null | undefined {
  return document.querySelector(".ant-steps-item-active .ant-steps-item-title")?.textContent;
}

describe("GenerateResumeModal 生成进度条", () => {
  it("renders a stage bar and a live received-character counter from the polled task", async () => {
    // 后台任务模型：start 返回 running 任务，随后轮询拿到真实 progress 文案与字数。
    apiMocks.startResumeGeneration.mockResolvedValue(makeTask());
    apiMocks.getResumeGenerateTask.mockResolvedValue(
      makeTask({ message: "正在调用模型 m 生成简历…", received_chars: 15 }),
    );

    renderModal();
    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    // 阶段条的每一步标题都渲染出来（antd Steps 会把已过 / 未到的步骤一并显示）
    expect(await screen.findByText("整理资料")).toBeInTheDocument();
    expect(screen.getByText("筛选资料")).toBeInTheDocument();
    expect(screen.getByText("调用模型生成")).toBeInTheDocument();

    // 轮询回来的 progress 文案推进阶段条，停在「调用模型生成」
    await waitFor(() => expect(activeStepTitle()).toBe("调用模型生成"));

    // 已接收字数直接取后端回填的 received_chars
    await waitFor(() => {
      expect(screen.getByText(/已接收 15 字/)).toBeInTheDocument();
    });
  });

  it("does not crash when the backend sends no progress message", async () => {
    // 后端没回填 message：阶段条停在第一步，字数照常显示，界面不崩。
    apiMocks.getResumeGenerateTask.mockResolvedValue(makeTask({ message: "", received_chars: 12 }));

    renderModal();
    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    expect(await screen.findByText(/正在准备/)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/已接收 12 字/)).toBeInTheDocument();
    });
    expect(activeStepTitle()).toBe("整理资料");
  });

  it("shows an unmappable progress message as text without advancing the stage", async () => {
    apiMocks.getResumeGenerateTask.mockResolvedValue(
      makeTask({ message: "一段后端新增、尚未认识的进度文案" }),
    );

    renderModal();
    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    // 映射不上就只显示原文，阶段条仍停在第一步，绝不硬凑一个不存在的步骤
    expect(await screen.findByText(/一段后端新增、尚未认识的进度文案/)).toBeInTheDocument();
    expect(activeStepTitle()).toBe("整理资料");
  });
});

describe("GenerateResumeModal 后台生成任务", () => {
  it("completes and opens the preview after polling a completed task", async () => {
    apiMocks.getResumeGenerateTask.mockResolvedValue(
      makeTask({ status: "completed", resume_id: 7 }),
    );
    apiMocks.getResume.mockResolvedValue(RESUME_DETAIL);
    apiMocks.renderResume.mockResolvedValue("<div>预览HTML</div>");

    renderModal();
    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    // 完成后取回简历记录并渲染预览
    await waitFor(() => expect(apiMocks.getResume).toHaveBeenCalledWith(7));
    expect(apiMocks.renderResume).toHaveBeenCalled();
    // 完成提醒由 utils/backgroundTasks 统一发。弹窗开着时只用右上角卡片（不弹居中弹窗
    // 打断用户），所以 modal 应为 false——"用户已经走开"才升级成居中弹窗（见 store 的测试）。
    await waitFor(() => expect(notices.length).toBeGreaterThan(0));
    expect(notices[0].title).toBe("简历已生成");
    expect(notices[0].modal).toBe(false);
  });

  it("treats a completed task without resume_id as an error instead of hanging", async () => {
    apiMocks.getResumeGenerateTask.mockResolvedValue(
      makeTask({ status: "completed", resume_id: null }),
    );

    renderModal();
    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    // 完成却缺 resume_id：不进预览、不取简历，而是明确报错并提供"重新生成"入口。
    expect(await screen.findByText("生成完成，但结果记录缺失，请重试")).toBeInTheDocument();
    expect(apiMocks.getResume).not.toHaveBeenCalled();
    expect(apiMocks.renderResume).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /重新生成/ })).toBeInTheDocument();
  });

  it("cancel calls the cancel API and returns to config", async () => {
    apiMocks.cancelResumeGenerateTask.mockResolvedValue(makeTask({ status: "cancelled" }));

    renderModal();
    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    const cancelBtn = await screen.findByRole("button", { name: /取消生成/ });
    fireEvent.click(cancelBtn);

    await waitFor(() => expect(apiMocks.cancelResumeGenerateTask).toHaveBeenCalledWith(1));
    // 终态 cancelled：回到配置页 + 提示已取消
    expect(await screen.findByText("已取消生成")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /开始生成/ })).toBeInTheDocument();
  });

  it("closing during generation continues in background without cancelling", async () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    const continueBtn = await screen.findByRole("button", { name: /后台继续/ });
    fireEvent.click(continueBtn);

    // 关弹窗 = 后台继续：不取消、不重复启动，只通知父组件收起。
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(apiMocks.cancelResumeGenerateTask).not.toHaveBeenCalled();
    expect(apiMocks.startResumeGeneration).toHaveBeenCalledOnce();
  });
});
