/** 离线分享包：生成只读快照、展示文件清单、下载文件、导入评论。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SharePackageModal from "./SharePackageModal";

const apiMocks = vi.hoisted(() => ({
  createSharePackage: vi.fn(),
  getSharePackageComments: vi.fn(),
  importSharePackageComments: vi.fn(),
  downloadSharePackageFile: vi.fn(),
  deleteSharePackage: vi.fn(),
  revealSharePackage: vi.fn(),
}));

const downloadMocks = vi.hoisted(() => ({
  downloadBlob: vi.fn(),
}));

const clipboardMocks = vi.hoisted(() => ({
  copyText: vi.fn(),
}));

vi.mock("../api/sharePackages", () => apiMocks);
vi.mock("../utils/download", () => downloadMocks);
vi.mock("../utils/clipboard", () => clipboardMocks);

const READ_ONLY = {
  id: 1,
  title: "张三-分享包-20260101",
  resume_id: 7,
  job_id: null,
  permission: "read_only",
  files: [
    {
      name: "resume.html",
      path: "C:\\tmp\\share\\1\\resume.html",
      format: "html",
      size: 100,
      sha256: "abc",
      download_url: "/api/share-packages/1/files/resume.html",
    },
    {
      name: "resume.pdf",
      path: "C:\\tmp\\share\\1\\resume.pdf",
      format: "pdf",
      size: 200,
      sha256: "def",
      download_url: "/api/share-packages/1/files/resume.pdf",
    },
  ],
  snapshot: { name: "***" },
  comments_file: "",
  share_token: "token123",
  redaction_config: {},
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

const COMMENT = {
  ...READ_ONLY,
  id: 2,
  permission: "comment",
  comments_file: "C:\\tmp\\share\\2\\comments.md",
  files: [
    ...READ_ONLY.files,
    {
      name: "comments.md",
      path: "C:\\tmp\\share\\2\\comments.md",
      format: "markdown",
      size: 50,
      sha256: "ghi",
      download_url: "/api/share-packages/2/files/comments.md",
    },
  ],
};

function renderModal() {
  return render(
    <AntdApp>
      <SharePackageModal recordId={7} open onClose={vi.fn()} />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.createSharePackage.mockReset().mockResolvedValue(READ_ONLY);
  apiMocks.getSharePackageComments.mockReset().mockResolvedValue({
    filename: "comments.md",
    format: "markdown",
    content: "初始评论",
  });
  apiMocks.importSharePackageComments.mockReset().mockResolvedValue({
    filename: "comments.md",
    format: "markdown",
    content: "新评论",
  });
  apiMocks.downloadSharePackageFile.mockReset().mockResolvedValue({
    blob: new Blob(["html"]),
    filename: "resume.html",
  });
  apiMocks.deleteSharePackage.mockReset().mockResolvedValue(undefined);
  apiMocks.revealSharePackage.mockReset().mockResolvedValue({
    directory: "C:\\tmp\\share\\1",
  });
  downloadMocks.downloadBlob.mockReset();
  clipboardMocks.copyText.mockReset().mockResolvedValue(true);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("SharePackageModal", () => {
  it("生成只读分享包并展示分享码与文件清单", async () => {
    renderModal();

    fireEvent.click(screen.getByRole("button", { name: "生成分享包" }));

    expect(await screen.findByText("token123")).toBeInTheDocument();
    expect(screen.getByText("resume.html")).toBeInTheDocument();
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(apiMocks.createSharePackage).toHaveBeenCalledWith(
      expect.objectContaining({
        resume_id: 7,
        permission: "read_only",
        redact_options: expect.objectContaining({ mask_name: true, mask_company: true }),
      }),
    );
  });

  it("下载文件走下载接口并触发浏览器下载", async () => {
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: "生成分享包" }));
    await screen.findByText("token123");

    fireEvent.click(screen.getByRole("button", { name: "resume.html" }));

    await waitFor(() => expect(apiMocks.downloadSharePackageFile).toHaveBeenCalledWith(1, "resume.html"));
    expect(downloadMocks.downloadBlob).toHaveBeenCalledTimes(1);
  });

  it("comment 权限生成后导入回传评论", async () => {
    apiMocks.createSharePackage.mockResolvedValue(COMMENT);
    renderModal();

    fireEvent.click(screen.getByRole("button", { name: "生成分享包" }));
    expect(await screen.findByText("初始评论")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("评论回传内容"), {
      target: { value: "新评论" },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入评论" }));

    await waitFor(() =>
      expect(apiMocks.importSharePackageComments).toHaveBeenCalledWith(2, {
        content: "新评论",
        format: "markdown",
      }),
    );
  });

  it("删除分享包需二次确认，确认后走删除接口并清空结果", async () => {
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: "生成分享包" }));
    await screen.findByText("token123");

    // 打开 Popconfirm（触发按钮含 DeleteOutlined 图标，accessible name 带 "delete" 前缀）。
    fireEvent.click(screen.getByRole("button", { name: /删除此分享包/ }));
    // 确认按钮带 aria-label，避免与触发按钮文案冲突。
    fireEvent.click(await screen.findByRole("button", { name: /确认删除分享包/ }));

    await waitFor(() => expect(apiMocks.deleteSharePackage).toHaveBeenCalledWith(1));
    await waitFor(() => expect(screen.queryByText("token123")).not.toBeInTheDocument());
  });

  it("展示使用说明，可打开所在文件夹并复制路径", async () => {
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: "生成分享包" }));
    await screen.findByText("token123");

    expect(screen.getByText(/把整个文件夹发给对方/)).toBeInTheDocument();
    expect(screen.getByText("使用说明")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /打开所在文件夹/ }));
    await waitFor(() => expect(apiMocks.revealSharePackage).toHaveBeenCalledWith(1));

    fireEvent.click(screen.getByRole("button", { name: /复制路径/ }));
    await waitFor(() =>
      expect(clipboardMocks.copyText).toHaveBeenCalledWith("C:\\tmp\\share\\1"),
    );
  });
});
