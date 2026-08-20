import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
