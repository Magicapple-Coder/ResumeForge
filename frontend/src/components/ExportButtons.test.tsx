/**
 * 导出按钮组：重点是"正文还有未完成标记"（409）那条分支。
 *
 * 这条分支有两件事必须同时成立：拦下时要**说清原因并给出去路**，用户点了"我去改简历"
 * 之后**不能再偷偷导出**。两头都错得很隐蔽——前者变成导出失败的死路，后者变成
 * 用户以为没导出、其实草稿已经下载了。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import ExportButtons from "./ExportButtons";

const apiMocks = vi.hoisted(() => ({
  exportResume: vi.fn(),
  fetchResumeHtml: vi.fn(),
}));

const downloadMocks = vi.hoisted(() => ({
  downloadBlob: vi.fn(),
  printHtml: vi.fn(),
}));

vi.mock("../api/resumes", () => apiMocks);
vi.mock("../utils/download", () => downloadMocks);

const BLOCKED = new ApiError(
  "这份简历里还有 1 处未完成标记：个人总结 里还有「【待补」。确实只想导出一份草稿自查时，可以选择「导出草稿」。",
  409,
);

const RESULT = {
  blob: new Blob(["pdf"]),
  filename: "简历.pdf",
  pages: 1,
  pageLimit: 1,
};

function renderButtons() {
  return render(
    <AntdApp>
      <ExportButtons recordId={7} />
    </AntdApp>,
  );
}

beforeEach(() => {
  for (const mock of [...Object.values(apiMocks), ...Object.values(downloadMocks)]) {
    mock.mockReset();
  }
});

afterEach(cleanup);

describe("ExportButtons", () => {
  it("downloads straight away when nothing is blocked", async () => {
    apiMocks.exportResume.mockResolvedValue(RESULT);
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: /下载 PDF/ }));

    await waitFor(() => expect(downloadMocks.downloadBlob).toHaveBeenCalledTimes(1));
    // 没有拦下时不该问任何问题。
    expect(screen.queryByText(/未完成标记/)).not.toBeInTheDocument();
    expect(apiMocks.exportResume).toHaveBeenCalledWith(7, "pdf", false);
  });

  it("explains why the export was blocked and offers a way out", async () => {
    apiMocks.exportResume.mockRejectedValueOnce(BLOCKED).mockResolvedValue(RESULT);
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: /下载 PDF/ }));

    // 原因要原样透出（后端已经写清是哪一节），并且给出"仍要导出草稿"这条路。
    expect(await screen.findByText(/个人总结 里还有/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "仍要导出草稿" }));

    await waitFor(() => expect(downloadMocks.downloadBlob).toHaveBeenCalledTimes(1));
    // 第二次必须显式带上"允许未完成"，而不是把同一个请求重发一遍。
    expect(apiMocks.exportResume).toHaveBeenNthCalledWith(2, 7, "pdf", true);
  });

  it("does not download anything when the user chooses to fix the resume first", async () => {
    apiMocks.exportResume.mockRejectedValue(BLOCKED);
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: /下载 PDF/ }));
    // 用正文里独有的那句匹配：标题和正文都含「未完成标记」，只按这个找会命中两个元素。
    expect(await screen.findByText(/个人总结 里还有/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "我去改简历" }));

    // 不断言"弹窗消失了"——那取决于 antd 的退场动画，不是这条测试要证明的事。
    await waitFor(() => expect(apiMocks.exportResume).toHaveBeenCalledTimes(1));
    expect(downloadMocks.downloadBlob).not.toHaveBeenCalled();
  });

  it("reports other errors without asking about placeholders", async () => {
    apiMocks.exportResume.mockRejectedValue(new ApiError("生成 PDF 失败", 500));
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: /下载 PDF/ }));

    expect(await screen.findByText(/生成 PDF 失败/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "仍要导出草稿" })).not.toBeInTheDocument();
    expect(downloadMocks.downloadBlob).not.toHaveBeenCalled();
  });

  it("applies the same gate to the other formats", async () => {
    apiMocks.exportResume.mockRejectedValueOnce(BLOCKED).mockResolvedValue({
      ...RESULT,
      filename: "简历.md",
    });
    renderButtons();

    // antd 的 Dropdown 默认 hover 触发，jsdom 里 click 打不开它。
    fireEvent.mouseEnter(screen.getByRole("button", { name: /更多格式/ }));
    fireEvent.click(await screen.findByText("导出 Markdown"));

    fireEvent.click(await screen.findByRole("button", { name: "仍要导出草稿" }));
    await waitFor(() => expect(downloadMocks.downloadBlob).toHaveBeenCalledTimes(1));
    expect(apiMocks.exportResume).toHaveBeenNthCalledWith(2, 7, "md", true);
  });
});
