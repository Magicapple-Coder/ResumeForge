/** 生成弹窗在「没有岗位」（通用简历）时的行为。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TEMPLATE_CATALOG } from "../test/resumeFixtures";
import GenerateResumeModal from "./GenerateResumeModal";

const apiMocks = vi.hoisted(() => ({
  generateResume: vi.fn(),
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
  generateResume: apiMocks.generateResume,
  renderResume: apiMocks.renderResume,
  updateResume: apiMocks.updateResume,
  updateResumeLayout: apiMocks.updateResumeLayout,
  fetchResumeTemplates: apiMocks.fetchResumeTemplates,
}));
vi.mock("../api/settings", () => ({ getLLMConfig: apiMocks.getLLMConfig }));

beforeEach(() => {
  apiMocks.generateResume.mockReset();
  apiMocks.renderResume.mockReset();
  apiMocks.updateResume.mockReset();
  apiMocks.updateResumeLayout.mockReset();
  apiMocks.fetchResumeTemplates.mockReset();
  apiMocks.getLLMConfig.mockReset();
  apiMocks.getLLMConfig.mockResolvedValue({ base_url: "https://api.example.com/v1", model: "m" });
  apiMocks.generateResume.mockResolvedValue(undefined);
  apiMocks.fetchResumeTemplates.mockResolvedValue(TEMPLATE_CATALOG);
});

afterEach(() => {
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

    await waitFor(() => expect(apiMocks.generateResume).toHaveBeenCalledOnce());
    expect(apiMocks.generateResume.mock.calls[0][0]).toMatchObject({
      job_id: null,
      title: "研发通用版",
    });
  });

  it("sends an empty title when the user leaves the name blank", async () => {
    renderModal();

    fireEvent.click(await screen.findByRole("button", { name: /开始生成/ }));

    await waitFor(() => expect(apiMocks.generateResume).toHaveBeenCalledOnce());
    // 留空交给后端按「姓名-通用简历-时间」命名
    expect(apiMocks.generateResume.mock.calls[0][0].title).toBe("");
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
