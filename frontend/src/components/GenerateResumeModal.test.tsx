/** 生成弹窗在「没有岗位」（通用简历）时的行为。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GenerateResumeModal from "./GenerateResumeModal";

const apiMocks = vi.hoisted(() => ({
  generateResume: vi.fn(),
  renderResume: vi.fn(),
  updateResume: vi.fn(),
  getLLMConfig: vi.fn(),
}));

vi.mock("../api/resumes", () => apiMocks);
vi.mock("../api/settings", () => ({ getLLMConfig: apiMocks.getLLMConfig }));

beforeEach(() => {
  apiMocks.generateResume.mockReset();
  apiMocks.renderResume.mockReset();
  apiMocks.updateResume.mockReset();
  apiMocks.getLLMConfig.mockReset();
  apiMocks.getLLMConfig.mockResolvedValue({ base_url: "https://api.example.com/v1", model: "m" });
  apiMocks.generateResume.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function renderModal(props: Partial<React.ComponentProps<typeof GenerateResumeModal>> = {}) {
  render(
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
