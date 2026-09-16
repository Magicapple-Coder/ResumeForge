import { App as AntdApp } from "antd";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Job } from "../types";
import JobsPage from "./JobsPage";

const apiMocks = vi.hoisted(() => ({ reload: vi.fn() }));

const JOB: Job = {
  id: 1,
  title: "护士",
  company: "示例医院",
  location: "杭州市余杭区",
  salary: "",
  job_type: "社招",
  description: "负责病区护理工作。",
  requirements: "持有护士执业资格证。",
  additional_info: "提供岗位培训。",
  keywords: [],
  source: "手动添加",
  source_url: "",
  posted_at: "2026年8月20日",
  status: "开放中",
  note: "",
  note_images: [],
  recognition_source: "",
  favorite: false,
  created_at: "2026-08-19T08:00:00",
  updated_at: "2026-08-21T09:30:00",
};

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data: { items: [JOB], total: 1 },
    loading: false,
    reload: apiMocks.reload,
    error: null,
  }),
}));

describe("JobsPage", () => {
  it("shows the recruitment posted date instead of the local update timestamp", () => {
    render(
      <AntdApp>
        <MemoryRouter>
          <JobsPage />
        </MemoryRouter>
      </AntdApp>,
    );

    expect(screen.getAllByText("发布时间").length).toBeGreaterThan(0);
    expect(screen.getByText("2026年8月20日")).toBeInTheDocument();
    expect(screen.queryByText("更新时间")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-08-21 17:30")).not.toBeInTheDocument();
  });
});
