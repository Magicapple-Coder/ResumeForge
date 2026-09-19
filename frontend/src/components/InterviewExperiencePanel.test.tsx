/** 面经知识库面板：列表渲染、真实问题清单展示、错误透出。 */
import { cleanup, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import InterviewExperiencePanel from "./InterviewExperiencePanel";

const apiMocks = vi.hoisted(() => ({
  listInterviewExperiences: vi.fn(),
  createInterviewExperience: vi.fn(),
  updateInterviewExperience: vi.fn(),
  deleteInterviewExperience: vi.fn(),
}));

vi.mock("../api/interviewExperiences", () => apiMocks);

const ITEMS = [
  {
    id: 1,
    title: "某司一面",
    company: "示例公司",
    position: "后端开发",
    job_id: null,
    content: "先问八股再深挖项目",
    questions: ["说一个你主导的项目", "这个指标怎么算的"],
    tags: ["后端", "一面"],
    source: "self",
    difficulty: "中等",
    round_type: "一面",
    interview_date: "2026-09-20",
    created_at: "2026-09-20T10:00:00",
    updated_at: "2026-09-20T10:00:00",
  },
];

beforeEach(() => {
  apiMocks.listInterviewExperiences.mockReset();
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("InterviewExperiencePanel", () => {
  it("渲染面经列表与真实问题清单", async () => {
    apiMocks.listInterviewExperiences.mockResolvedValue(ITEMS);
    render(
      <AntApp>
        <InterviewExperiencePanel jobOptions={[]} />
      </AntApp>,
    );

    expect(await screen.findByText("某司一面")).toBeInTheDocument();
    expect(screen.getByText(/示例公司/)).toBeInTheDocument();
    expect(screen.getByText(/真实问题 2 个/)).toBeInTheDocument();
    expect(screen.getByText(/说一个你主导的项目/)).toBeInTheDocument();
    expect(apiMocks.listInterviewExperiences).toHaveBeenCalled();
  });

  it("读取失败时透出中文错误", async () => {
    apiMocks.listInterviewExperiences.mockRejectedValue(new Error("读取面经失败"));
    render(
      <AntApp>
        <InterviewExperiencePanel jobOptions={[]} />
      </AntApp>,
    );

    expect(await screen.findByText("读取面经失败")).toBeInTheDocument();
  });
});
