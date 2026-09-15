/** 通用简历区块：只查通用简历、重命名、删除与两个创建入口。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GeneralResumeSection from "./GeneralResumeSection";

const apiMocks = vi.hoisted(() => ({
  deleteResume: vi.fn(),
  listResumes: vi.fn(),
  renameResume: vi.fn(),
  getResume: vi.fn(),
  fetchResumeHtml: vi.fn(),
  renderResume: vi.fn(),
  updateResume: vi.fn(),
}));

vi.mock("../../api/resumes", () => apiMocks);

const GENERAL = {
  id: 7,
  title: "研发通用版",
  job_id: null,
  job_title: "后端开发",
  company: "",
  source: "ai" as const,
  favorite: false,
  model: "m",
  enhancement_enabled: false,
  enhancement_level: "balanced" as const,
  created_at: "2026-09-16T10:00:00",
};

function renderSection(overrides: Partial<React.ComponentProps<typeof GeneralResumeSection>> = {}) {
  const props = { onGenerate: vi.fn(), onWrite: vi.fn(), ...overrides };
  render(
    // 区块内嵌了 ResumeDetailModal，它需要 Router 上下文。
    <MemoryRouter>
      <AntdApp>
        <GeneralResumeSection {...props} />
      </AntdApp>
    </MemoryRouter>,
  );
  return props;
}

beforeEach(() => {
  apiMocks.listResumes.mockReset();
  apiMocks.renameResume.mockReset();
  apiMocks.deleteResume.mockReset();
  apiMocks.listResumes.mockResolvedValue({ items: [GENERAL], total: 1 });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("GeneralResumeSection", () => {
  it("asks only for general resumes and shows the intent instead of a job", async () => {
    renderSection();

    await waitFor(() => expect(apiMocks.listResumes).toHaveBeenCalledOnce());
    expect(apiMocks.listResumes.mock.calls[0][0]).toMatchObject({ has_job: false });
    const title = await screen.findByText("研发通用版");
    // 「通用简历」既是卡片标题也是每行的标签，这里限定在该行内查
    const row = title.closest("li");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("通用简历")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText(/求职意向：后端开发/)).toBeInTheDocument();
  });

  it("shows an empty state before anything is created", async () => {
    apiMocks.listResumes.mockResolvedValue({ items: [], total: 0 });

    renderSection();

    expect(await screen.findByText("还没有通用简历")).toBeInTheDocument();
  });

  it("hands the typed name to both creation entries", async () => {
    const props = renderSection();
    await screen.findByText("研发通用版");

    fireEvent.change(screen.getByLabelText("通用简历名称"), {
      target: { value: "管培生版" },
    });
    fireEvent.click(screen.getByRole("button", { name: /AI 生成/ }));
    fireEvent.click(screen.getByRole("button", { name: /从头手写/ }));

    expect(props.onGenerate).toHaveBeenCalledWith("管培生版");
    expect(props.onWrite).toHaveBeenCalledWith("管培生版");
  });

  it("renames in place", async () => {
    apiMocks.renameResume.mockResolvedValue({ ...GENERAL, title: "研发通用版 v2" });
    renderSection();
    await screen.findByText("研发通用版");

    fireEvent.click(screen.getByRole("button", { name: "重命名通用简历 研发通用版" }));
    fireEvent.change(screen.getByLabelText("重命名输入框"), {
      target: { value: "研发通用版 v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => expect(apiMocks.renameResume).toHaveBeenCalledWith(7, "研发通用版 v2"));
    expect(await screen.findByText("研发通用版 v2")).toBeInTheDocument();
  });

  it("deletes only after confirmation", async () => {
    apiMocks.deleteResume.mockResolvedValue(undefined);
    renderSection();
    await screen.findByText("研发通用版");

    fireEvent.click(screen.getByRole("button", { name: "删除通用简历 研发通用版" }));

    expect(apiMocks.deleteResume).not.toHaveBeenCalled();
    const confirm = await waitFor(() =>
      document.querySelector<HTMLButtonElement>(".ant-popconfirm-buttons .ant-btn-primary")!,
    );
    fireEvent.click(confirm);

    await waitFor(() => expect(apiMocks.deleteResume).toHaveBeenCalledWith(7));
    expect(await screen.findByText("还没有通用简历")).toBeInTheDocument();
  });
});
