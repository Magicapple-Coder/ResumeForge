/** 投递记录：横向不溢出（无 scroll.x）、长文本硬截断、详情 Drawer 展示完整失败信息（含 URL）。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyRecord, Page } from "../../types";
import ApplyRecordsPanel from "./ApplyRecordsPanel";

const apiMocks = vi.hoisted(() => ({
  listRecords: vi.fn(),
  retryRecord: vi.fn(),
}));

vi.mock("../../api/apply", () => ({
  listRecords: apiMocks.listRecords,
  retryRecord: apiMocks.retryRecord,
}));

const RECORD: ApplyRecord = {
  id: 1,
  task_id: 7,
  job_id: 11,
  job_title: "高级后端工程师（高并发方向）",
  company: "某知名互联网科技有限公司",
  resume_title: "后端开发岗位版简历",
  greeting: "您好，我看到贵司的岗位非常契合我的经验，希望能进一步沟通。",
  status: "failed",
  failure_category: "selector_invalid",
  failure_label: "",
  failure_detail:
    "页面结构变化：投递表单的选择器已失效。失败页面 URL：https://example.com/job/12345 ，页面标题：「职位申请 - 某某招聘」",
  attempt: 2,
  created_at: "2026-09-17T08:00:00",
  finished_at: "2026-09-17T08:05:00",
};

const PAGE: Page<ApplyRecord> = { items: [RECORD], total: 1 };

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.listRecords.mockResolvedValue(PAGE);
  apiMocks.retryRecord.mockResolvedValue({ id: 99 } as never);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ApplyRecordsPanel", () => {
  it("renders records and exposes a 详情 button per row", async () => {
    render(
      <AntdApp>
        <ApplyRecordsPanel disabled={false} onRetried={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("高级后端工程师（高并发方向）")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /详\s*情/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重投/ })).toBeInTheDocument();
  });

  it("opens a right-side Drawer that shows the full failure detail including the URL", async () => {
    render(
      <AntdApp>
        <ApplyRecordsPanel disabled={false} onRetried={vi.fn()} />
      </AntdApp>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /详\s*情/ }));

    // Drawer 完整展示失败信息（含 URL、页面标题）与招呼语全文，不做截断。
    // 招呼语在表格列里也有（视觉截断但仍在 DOM），因此把断言范围限定在 Drawer 内。
    const drawer = await screen.findByRole("dialog");
    expect(
      within(drawer).getByText(/失败页面 URL：https:\/\/example\.com\/job\/12345/),
    ).toBeInTheDocument();
    expect(within(drawer).getByText(/页面标题：「职位申请 - 某某招聘」/)).toBeInTheDocument();
    expect(within(drawer).getByText(/批次 #7 · 第 2 次尝试/)).toBeInTheDocument();
    expect(within(drawer).getByText(/您好，我看到贵司的岗位非常契合我的经验/)).toBeInTheDocument();
  });

  it("does not enable a horizontal scroll bar (no scroll.x on the table)", async () => {
    const { container } = render(
      <AntdApp>
        <ApplyRecordsPanel disabled={false} onRetried={vi.fn()} />
      </AntdApp>,
    );
    await screen.findByText("高级后端工程师（高并发方向）");

    // scroll.x 未设置：AntD 不会渲染横向滚动容器 .ant-table-content（它是 scroll.x 专属）。
    expect(container.querySelector(".ant-table-content")).toBeNull();
    // 纵向滚动容器仍在（scroll.y），列表高度受限、可纵向滚动。
    expect(container.querySelector(".ant-table-body")).not.toBeNull();
  });
});
