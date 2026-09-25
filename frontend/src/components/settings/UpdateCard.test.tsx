/** 软件更新卡片：检查、下载进度与后台下载选项。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import UpdateCard from "./UpdateCard";

const apiMocks = vi.hoisted(() => ({
  checkForUpdate: vi.fn(),
  getUpdateDownloadStatus: vi.fn(),
  startUpdateDownload: vi.fn(),
  installDownloadedUpdate: vi.fn(),
}));

vi.mock("../../api/settings", () => apiMocks);

const latest = {
  current_version: "0.11.0",
  latest_version: "0.12.0",
  update_available: true,
  release_name: "新版本",
  release_url: "https://example.com/release",
  published_at: "2026-09-24T00:00:00Z",
  notes: "修复问题",
  message: "有新版本 0.12.0 可用",
  checked_at: "2026-09-24T00:00:00Z",
  download_url: "https://example.com/update.zip",
  download_size: 2048,
  asset_name: "ResumeForge-0.12.0.zip",
  installable: true,
};

function renderCard() {
  return render(
    <AntdApp>
      <UpdateCard />
    </AntdApp>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  apiMocks.getUpdateDownloadStatus.mockResolvedValue({
    state: "idle",
    current_version: "0.11.0",
    target_version: "",
    progress: 0,
    downloaded_bytes: 0,
    total_bytes: null,
    background: false,
    installable: false,
    message: "",
  });
  apiMocks.checkForUpdate.mockResolvedValue(latest);
  apiMocks.startUpdateDownload.mockResolvedValue({
    state: "ready",
    current_version: "0.11.0",
    target_version: "0.12.0",
    progress: 100,
    downloaded_bytes: 2048,
    total_bytes: 2048,
    background: true,
    installable: true,
    message: "更新包已下载完成，可以重启安装",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("UpdateCard", () => {
  it("checks for updates, offers background download, and shows the ready state", async () => {
    renderCard();
    await waitFor(() => expect(apiMocks.getUpdateDownloadStatus).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: "检查更新" }));
    expect(await screen.findByRole("button", { name: "下载更新" })).toBeEnabled();

    const backgroundSwitch = screen.getByRole("switch");
    fireEvent.click(backgroundSwitch);
    expect(backgroundSwitch).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "下载更新" }));

    await waitFor(() => expect(apiMocks.startUpdateDownload).toHaveBeenCalledWith(true));
    expect(await screen.findByText("更新包已下载完成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重启并安装" })).toBeInTheDocument();
  });
});
