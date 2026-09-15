/** 我的资料页：通用简历入口的接线（这个页面此前没有任何测试）。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Profile } from "../types";
import ProfilePage from "./ProfilePage";

const apiMocks = vi.hoisted(() => ({
  getProfile: vi.fn(),
  listResumes: vi.fn(),
}));

vi.mock("../api/profile", () => ({ getProfile: apiMocks.getProfile }));
vi.mock("../api/resumes", () => ({
  listResumes: apiMocks.listResumes,
  deleteResume: vi.fn(),
  renameResume: vi.fn(),
  getResume: vi.fn(),
  fetchResumeHtml: vi.fn(),
  renderResume: vi.fn(),
  updateResume: vi.fn(),
  generateResume: vi.fn(),
  createManualResume: vi.fn(),
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
  it("renders the general-resume card outside of edit mode", async () => {
    renderPage();

    // 资料页很长，卡片在底部：头部要给一个直达入口
    expect(await screen.findByRole("button", { name: /通用简历/ })).toBeInTheDocument();
    // 非编辑状态也要能用：写简历不是改资料
    expect(screen.getByLabelText("通用简历名称")).toBeEnabled();
    expect(screen.getByRole("button", { name: /AI 生成/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /从头手写/ })).toBeEnabled();
    expect(await screen.findByText("还没有通用简历")).toBeInTheDocument();
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
