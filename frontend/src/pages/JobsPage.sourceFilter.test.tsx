/** 岗位广场：按来源（手动添加 / 自动采集）筛选的接线。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JobsPage from "./JobsPage";

const apiMocks = vi.hoisted(() => ({
  listJobs: vi.fn(),
}));

// 只覆盖 listJobs，其余 jobs API 保持真实导出（JobsPage 会 import 多个，漏一个会让它变 undefined）。
vi.mock("../api/jobs", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/jobs")>()),
  listJobs: apiMocks.listJobs,
}));
// startBackfill 只在点击「补齐详情」时才会用，这里保证它在 import 时存在即可。
vi.mock("../api/apply", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/apply")>()),
  startBackfill: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <AntdApp>
        <JobsPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

/** 打开「来源」下拉并选中指定项；「手动添加」同时也是一颗工具栏按钮，所以只认下拉选项容器里的文本。 */
async function selectSourceOption(label: string) {
  const combobox = screen.getByRole("combobox", { name: "来源筛选" });
  fireEvent.mouseDown(combobox);
  const option = await screen.findByText(
    (content, element) => content === label && !!element?.closest(".ant-select-item-option"),
  );
  fireEvent.click(option);
}

beforeEach(() => {
  apiMocks.listJobs.mockReset().mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("JobsPage 来源筛选", () => {
  it("初始不带 source_kind 参数", async () => {
    renderPage();

    await waitFor(() => expect(apiMocks.listJobs).toHaveBeenCalled());
    expect(apiMocks.listJobs).not.toHaveBeenCalledWith(
      expect.objectContaining({ source_kind: expect.anything() }),
    );
  });

  it("选「自动采集」后按 collected 重新拉取", async () => {
    renderPage();
    await waitFor(() => expect(apiMocks.listJobs).toHaveBeenCalled());

    await selectSourceOption("自动采集");

    await waitFor(() =>
      expect(apiMocks.listJobs).toHaveBeenCalledWith(
        expect.objectContaining({ source_kind: "collected" }),
      ),
    );
  });

  it("选「手动添加」后按 manual 重新拉取", async () => {
    renderPage();
    await waitFor(() => expect(apiMocks.listJobs).toHaveBeenCalled());

    await selectSourceOption("手动添加");

    await waitFor(() =>
      expect(apiMocks.listJobs).toHaveBeenCalledWith(
        expect.objectContaining({ source_kind: "manual" }),
      ),
    );
  });
});
