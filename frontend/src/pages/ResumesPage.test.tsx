import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ResumeBrief } from "../types";
import ResumesPage from "./ResumesPage";

const apiMocks = vi.hoisted(() => ({
  deleteResume: vi.fn(),
  listResumes: vi.fn(),
  updateResumeFavorite: vi.fn(),
}));

vi.mock("../api/resumes", () => ({
  deleteResume: apiMocks.deleteResume,
  listResumes: apiMocks.listResumes,
  updateResumeFavorite: apiMocks.updateResumeFavorite,
  getResume: vi.fn(),
  fetchResumeHtml: vi.fn(),
  renderResume: vi.fn(),
  updateResume: vi.fn(),
}));

const RESUME: ResumeBrief = {
  id: 8,
  title: "制造工程师岗位简历",
  job_id: 3,
  job_title: "制造工程师",
  company: "示例制造企业",
  source: "manual",
  favorite: false,
  model: "",
  enhancement_enabled: false,
  enhancement_level: "balanced",
  created_at: "2026-08-20T10:00:00",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AntdApp>
        <ResumesPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiMocks.listResumes.mockReset().mockResolvedValue({ items: [RESUME], total: 1 });
  apiMocks.updateResumeFavorite.mockReset().mockResolvedValue({});
  apiMocks.deleteResume.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ResumesPage column hints", () => {
  it("explains what a beauty-enhancement level actually did on hover", async () => {
    apiMocks.listResumes.mockResolvedValue({
      items: [{ ...RESUME, enhancement_enabled: true, enhancement_level: "balanced" }],
      total: 1,
    });
    renderPage();
    await screen.findByText(RESUME.title);

    // “均衡”两个字本身说明不了什么，悬停要给出这一档做了什么。
    fireEvent.mouseEnter(screen.getByText("均衡"));

    expect(await screen.findByRole("tooltip")).toHaveTextContent("补足方法、技术细节与成果表达");
  });

  it("explains what a general resume is on hover", async () => {
    apiMocks.listResumes.mockResolvedValue({
      items: [{ ...RESUME, job_id: null, job_title: "软件开发" }],
      total: 1,
    });
    renderPage();
    await screen.findByText(RESUME.title);

    fireEvent.mouseEnter(screen.getByText("通用简历"));

    expect(await screen.findByRole("tooltip")).toHaveTextContent("不关联岗位、可投递多个方向");
  });
});

describe("ResumesPage favorites", () => {
  it("favorites a resume and blocks duplicate submissions while the update is pending", async () => {
    let resolveUpdate!: () => void;
    apiMocks.updateResumeFavorite.mockImplementation(
      () => new Promise<void>((resolve) => (resolveUpdate = resolve)),
    );
    renderPage();
    await screen.findByText(RESUME.title);
    const favoriteButton = screen.getByRole("button", { name: "收藏简历" });

    fireEvent.click(favoriteButton);
    fireEvent.click(favoriteButton);

    expect(apiMocks.updateResumeFavorite).toHaveBeenCalledWith(RESUME.id, true);
    expect(apiMocks.updateResumeFavorite).toHaveBeenCalledOnce();
    expect(favoriteButton).toBeDisabled();
    resolveUpdate();
    await waitFor(() => expect(apiMocks.listResumes).toHaveBeenCalledTimes(2));
  });

  it("uses the same control to remove an existing favorite", async () => {
    apiMocks.listResumes.mockResolvedValue({
      items: [{ ...RESUME, favorite: true }],
      total: 1,
    });
    renderPage();
    await screen.findByText(RESUME.title);

    fireEvent.click(screen.getByRole("button", { name: "取消收藏简历" }));

    await waitFor(() =>
      expect(apiMocks.updateResumeFavorite).toHaveBeenCalledWith(RESUME.id, false),
    );
  });
});

describe("ResumesPage 通用简历", () => {
  it("marks a job-less record as 通用简历 and shows the intent instead of a job", async () => {
    // 无岗位记录的 job_title 存的是求职意向，以前会被当成岗位名显示，
    // 于是通用简历看起来和岗位简历一模一样。
    apiMocks.listResumes.mockResolvedValue({
      items: [{ ...RESUME, job_id: null, job_title: "后端开发", company: "" }],
      total: 1,
    });
    renderPage();

    const row = (await screen.findByText(RESUME.title)).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("通用简历")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("求职意向：后端开发")).toBeInTheDocument();
    // 有岗位时岗位名是一个可点击跳转的按钮；通用简历不该有
    expect(within(row as HTMLElement).queryByRole("button", { name: RESUME.job_title })).toBeNull();
  });

  it("keeps job-linked records linking to their job", async () => {
    renderPage();

    const row = (await screen.findByText(RESUME.title)).closest("tr");
    expect(within(row as HTMLElement).getByText(RESUME.job_title)).toBeInTheDocument();
    expect(within(row as HTMLElement).queryByText("通用简历")).toBeNull();
  });
});
