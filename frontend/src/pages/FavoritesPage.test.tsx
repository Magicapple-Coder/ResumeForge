import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FavoritesPage from "./FavoritesPage";

const apiMocks = vi.hoisted(() => ({
  listJobs: vi.fn(),
  updateJob: vi.fn(),
  listResumes: vi.fn(),
  updateResumeFavorite: vi.fn(),
}));

vi.mock("../api/jobs", () => ({
  listJobs: apiMocks.listJobs,
  updateJob: apiMocks.updateJob,
}));
vi.mock("../api/resumes", () => ({
  listResumes: apiMocks.listResumes,
  updateResumeFavorite: apiMocks.updateResumeFavorite,
  getResume: vi.fn(),
  fetchResumeHtml: vi.fn(),
  renderResume: vi.fn(),
  updateResume: vi.fn(),
}));

beforeEach(() => {
  apiMocks.listJobs.mockReset().mockResolvedValue({
    items: [
      {
        id: 1,
        title: "数据分析师",
        company: "示例公司",
        location: "上海",
        posted_at: "2026-08-20",
        favorite: true,
      },
    ],
    total: 1,
  });
  apiMocks.listResumes.mockReset().mockResolvedValue({
    items: [
      {
        id: 2,
        title: "数据分析岗位简历",
        job_id: 1,
        job_title: "数据分析师",
        company: "示例公司",
        source: "ai",
        favorite: true,
        model: "test-model",
        enhancement_enabled: false,
        enhancement_level: "balanced",
        created_at: "2026-08-20T10:00:00",
      },
    ],
    total: 1,
  });
  apiMocks.updateJob.mockReset().mockResolvedValue({});
  apiMocks.updateResumeFavorite.mockReset().mockResolvedValue({});
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function renderPage() {
  return render(
    <MemoryRouter>
      <AntdApp>
        <FavoritesPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

describe("FavoritesPage", () => {
  it("loads only favorites and switches between jobs and resumes", async () => {
    renderPage();

    expect(await screen.findByText("数据分析师")).toBeInTheDocument();
    expect(apiMocks.listJobs).toHaveBeenCalledWith(expect.objectContaining({ favorite: true }));

    fireEvent.click(screen.getByText("简历"));
    expect(await screen.findByText("数据分析岗位简历")).toBeInTheDocument();
    await waitFor(() =>
      expect(apiMocks.listResumes).toHaveBeenCalledWith(
        expect.objectContaining({ favorite: true }),
      ),
    );
  });

  it("removes a job favorite once and reloads the filtered list", async () => {
    renderPage();
    await screen.findByText("数据分析师");
    const button = screen.getByRole("button", { name: "取消收藏" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(apiMocks.updateJob).toHaveBeenCalledWith(1, { favorite: false }));
    expect(apiMocks.updateJob).toHaveBeenCalledOnce();
    await waitFor(() => expect(apiMocks.listJobs).toHaveBeenCalledTimes(2));
  });

  it("removes a resume favorite through the resume API", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("简历"));
    await screen.findByText("数据分析岗位简历");

    fireEvent.click(screen.getByRole("button", { name: "取消收藏" }));

    await waitFor(() => expect(apiMocks.updateResumeFavorite).toHaveBeenCalledWith(2, false));
    await waitFor(() => expect(apiMocks.listResumes).toHaveBeenCalledTimes(2));
  });

  it("shows an update error and allows the user to retry", async () => {
    apiMocks.updateJob.mockRejectedValueOnce(new Error("收藏服务暂时不可用"));
    renderPage();
    await screen.findByText("数据分析师");

    fireEvent.click(screen.getByRole("button", { name: "取消收藏" }));
    expect(await screen.findByText("收藏服务暂时不可用")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "取消收藏" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "取消收藏" }));

    await waitFor(() => expect(apiMocks.updateJob).toHaveBeenCalledTimes(2));
  });
});
