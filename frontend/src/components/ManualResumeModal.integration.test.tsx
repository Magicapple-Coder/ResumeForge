import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, Profile } from "../types";
import ManualResumeModal from "./ManualResumeModal";

const apiMocks = vi.hoisted(() => ({
  createManualResume: vi.fn(),
  getProfile: vi.fn(),
}));

vi.mock("../api/resumes", () => ({ createManualResume: apiMocks.createManualResume }));
vi.mock("../api/profile", () => ({ getProfile: apiMocks.getProfile }));

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
  job_intent: "",
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

const JOB: Job = {
  id: 9,
  title: "机械设计工程师",
  company: "示例制造企业",
  location: "苏州",
  salary: "",
  job_type: "校招",
  description: "负责机械结构方案设计与样机验证。",
  requirements: "熟悉机械原理和工程制图。",
  additional_info: "提供生产基地轮岗机会。",
  keywords: [{ name: "工程制图", category: "通用能力" }],
  source: "手动添加",
  source_url: "",
  posted_at: "",
  status: "开放中",
  note: "",
  note_images: [],
  recognition_source: "",
  favorite: false,
  created_at: "2026-08-20T09:00:00",
  updated_at: "2026-08-20T09:00:00",
};

beforeEach(() => {
  apiMocks.createManualResume.mockReset();
  apiMocks.getProfile.mockReset();
  apiMocks.getProfile.mockResolvedValue(PROFILE);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ManualResumeModal", () => {
  it("passes the selected job into the resume editor as a reference", async () => {
    render(
      <AntdApp>
        <ManualResumeModal job={JOB} open onClose={vi.fn()} />
      </AntdApp>,
    );

    await waitFor(() => expect(apiMocks.getProfile).toHaveBeenCalledOnce());
    const referenceToggle = await screen.findByRole("button", { name: /查看岗位要求/ });
    fireEvent.click(referenceToggle);

    expect(screen.getByText(JOB.description)).toBeInTheDocument();
    expect(screen.getByText(JOB.requirements)).toBeInTheDocument();
    expect(screen.getByText(JOB.additional_info)).toBeInTheDocument();
    expect(screen.getByText("工程制图")).toBeInTheDocument();
    expect(screen.getByLabelText("求职意向")).toHaveValue(JOB.title);
  });

  it("opens the editor for a job-less general resume", async () => {
    // 以前这里会因为 !job 提前返回：资料不加载、编辑器永远打不开。
    render(
      <AntdApp>
        <ManualResumeModal job={null} open initialTitle="研发通用版" onClose={vi.fn()} />
      </AntdApp>,
    );

    await waitFor(() => expect(apiMocks.getProfile).toHaveBeenCalledOnce());
    expect(await screen.findByText("从头编写通用简历")).toBeInTheDocument();
    // 没有岗位就不该出现岗位要求面板
    expect(screen.queryByRole("button", { name: /查看岗位要求/ })).not.toBeInTheDocument();

    apiMocks.createManualResume.mockResolvedValue({ id: 1 });
    fireEvent.click(screen.getByRole("button", { name: /保存手写简历/ }));

    await waitFor(() => expect(apiMocks.createManualResume).toHaveBeenCalledOnce());
    expect(apiMocks.createManualResume.mock.calls[0][0]).toMatchObject({
      job_id: null,
      title: "研发通用版",
    });
  });
});
