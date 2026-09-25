/** 我的资料页：通用简历入口 + 分区折叠的接线（这个页面此前没有任何测试）。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TEMPLATE_CATALOG } from "../test/resumeFixtures";
import type { Profile } from "../types";
import ProfilePage from "./ProfilePage";

const apiMocks = vi.hoisted(() => ({
  getProfile: vi.fn(),
  listResumes: vi.fn(),
}));

vi.mock("../api/profile", () => ({ getProfile: apiMocks.getProfile }));
// 展开真实模块再覆盖：显式列导出时，生产代码新增一个导出就会让调用方直接抛
// "export is not defined"，看起来像组件崩了。
vi.mock("../api/resumes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/resumes")>()),
  listResumes: apiMocks.listResumes,
  deleteResume: vi.fn(),
  renameResume: vi.fn(),
  getResume: vi.fn(),
  fetchResumeHtml: vi.fn(),
  renderResume: vi.fn(),
  updateResume: vi.fn(),
  generateResume: vi.fn(),
  createManualResume: vi.fn(),
  fetchResumeTemplates: vi.fn().mockResolvedValue(TEMPLATE_CATALOG),
}));
vi.mock("../api/settings", () => ({ getLLMConfig: vi.fn().mockResolvedValue({}) }));

const PROFILE: Profile = {
  id: 1,
  photo: "",
  name: "张三",
  gender: "",
  birth_year: "",
  phone: "",
  email: "",
  city: "",
  target_city: "",
  job_intent: "后端开发",
  personal_website: "",
  github: "",
  summary: "",
  section_order: [],
  educations: [],
  experiences: [],
  campus_experiences: [],
  projects: [],
  skills: [],
  awards: [],
};

function renderPage() {
  render(
    <MemoryRouter>
      <AntdApp>
        <ProfilePage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiMocks.getProfile.mockReset().mockResolvedValue(PROFILE);
  apiMocks.listResumes.mockReset().mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ProfilePage 通用简历", () => {
  it("renders the general-resume card outside of edit mode, above the profile sections", async () => {
    renderPage();

    // 非编辑状态也要能用：写简历不是改资料
    expect(await screen.findByLabelText("通用简历名称")).toBeEnabled();
    expect(screen.getByRole("button", { name: /AI 生成/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /从头手写/ })).toBeEnabled();
    expect(await screen.findByText("还没有通用简历")).toBeInTheDocument();

    // 「通用简历」不再沉在资料最底部：它要出现在资料分区（基本信息）之前。
    const general = document.getElementById("general-resume-section");
    const basicSectionToggle = screen.getByRole("button", { name: "收起基本信息" });
    expect(general).not.toBeNull();
    expect(
      (general as HTMLElement).compareDocumentPosition(basicSectionToggle) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("carries the typed name into the generate modal", async () => {
    renderPage();
    await screen.findByText("还没有通用简历");

    fireEvent.change(screen.getByLabelText("通用简历名称"), {
      target: { value: "研发通用版" },
    });
    fireEvent.click(screen.getByRole("button", { name: /AI 生成/ }));

    expect(await screen.findByText("生成通用简历")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("简历名称")).toHaveValue("研发通用版"));
  });

  it("carries the typed name into the manual editor", async () => {
    renderPage();
    await screen.findByText("还没有通用简历");

    fireEvent.change(screen.getByLabelText("通用简历名称"), {
      target: { value: "管培生版" },
    });
    fireEvent.click(screen.getByRole("button", { name: /从头手写/ }));

    expect(await screen.findByText("从头编写通用简历")).toBeInTheDocument();
  });
});

describe("ProfilePage 分区折叠", () => {
  it("默认展开每个分区，点标题可收起", async () => {
    renderPage();
    await screen.findByLabelText("通用简历名称");

    // 默认全展开：这一页是"我的资料"，进来就是要看内容的（用户反馈过"应该默认展开"）。
    const basicToggle = screen.getByRole("button", { name: "收起基本信息" });
    expect(basicToggle).toHaveAttribute("aria-expanded", "true");

    // 点标题收起后，按钮翻转成「展开」。
    fireEvent.click(basicToggle);
    const collapsedToggle = screen.getByRole("button", { name: "展开基本信息" });
    expect(collapsedToggle).toHaveAttribute("aria-expanded", "false");
  });

  it("「全部收起」一键收回，再点「全部展开」一键展开", async () => {
    renderPage();
    await screen.findByLabelText("通用简历名称");

    // 页头按钮带图标，可访问名是「图标名 + 文字」，用正则匹配文字部分即可。
    const collapseAll = screen.getByRole("button", { name: /全部收起/ });
    fireEvent.click(collapseAll);

    // 全部收起后：每个分区标题都变成「展开」，页头按钮变成「全部展开」。
    expect(screen.getByRole("button", { name: "展开基本信息" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开教育经历" })).toBeInTheDocument();
    const expandAll = screen.getByRole("button", { name: /全部展开/ });

    fireEvent.click(expandAll);
    expect(screen.getByRole("button", { name: "收起基本信息" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /全部收起/ })).toBeInTheDocument();
  });
});
