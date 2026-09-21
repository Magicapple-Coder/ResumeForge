/** 投递记录（按批次分组）：组头统计、展开看明细、详情 Drawer 完整失败信息（含 URL）。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyRecord, ApplyRecordBatch, Page } from "../../types";
import ApplyRecordsPanel from "./ApplyRecordsPanel";

const apiMocks = vi.hoisted(() => ({
  listRecordBatches: vi.fn(),
  retryRecord: vi.fn(),
}));

vi.mock("../../api/apply", () => ({
  listRecordBatches: apiMocks.listRecordBatches,
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

const RECORD_SUCCESS: ApplyRecord = {
  ...RECORD,
  id: 2,
  job_title: "全栈工程师",
  company: "另一家公司",
  status: "success",
  failure_category: "",
  failure_label: "",
  failure_detail: "",
};

const BATCHES: Page<ApplyRecordBatch> = {
  items: [
    {
      id: 7,
      status: "completed",
      total: 3,
      processed: 3,
      succeeded: 1,
      failed: 1,
      skipped: 1,
      message: "投递任务已完成",
      created_at: "2026-09-17T08:00:00",
      finished_at: "2026-09-17T08:05:00",
      items: [RECORD, RECORD_SUCCESS],
    },
    {
      id: 6,
      status: "failed",
      total: 1,
      processed: 1,
      succeeded: 0,
      failed: 1,
      skipped: 0,
      message: "",
      created_at: "2026-09-16T08:00:00",
      finished_at: "2026-09-16T08:01:00",
      items: [],
    },
  ],
  total: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.listRecordBatches.mockResolvedValue(BATCHES);
  apiMocks.retryRecord.mockResolvedValue({ id: 99 } as never);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

async function renderPanel() {
  render(
    <AntdApp>
      <ApplyRecordsPanel disabled={false} onRetried={vi.fn()} />
    </AntdApp>,
  );
  // 等组头渲染完成。
  await screen.findByTestId("record-batch-7");
}

/** 取某个批次的组头按钮（批次卡片里可能有多个 button，组头有专属 class）。 */
function batchHead(batchId: number): HTMLElement {
  const card = screen.getByTestId(`record-batch-${batchId}`);
  const head = card.querySelector<HTMLElement>("button.apply-records-batch-head");
  if (!head) throw new Error(`batch #${batchId} head not found`);
  return head;
}

describe("ApplyRecordsPanel (grouped by batch)", () => {
  it("renders one collapsed group per batch with batch-level stats", async () => {
    await renderPanel();

    expect(screen.getByTestId("record-batch-7")).toBeInTheDocument();
    expect(screen.getByTestId("record-batch-6")).toBeInTheDocument();
    // 组头展示批次号与统计（成功/失败/跳过是该批次自己的账）。
    const head7 = within(screen.getByTestId("record-batch-7")).getByRole("button");
    expect(within(head7).getByText("批次 #7")).toBeInTheDocument();
    expect(within(head7).getByText(/成功 1/)).toBeInTheDocument();
    expect(within(head7).getByText(/失败 1/)).toBeInTheDocument();
    // 未展开时看不到岗位明细。
    expect(screen.queryByText("高级后端工程师（高并发方向）")).not.toBeInTheDocument();
  });

  it("expands a batch to reveal its records, then collapses again", async () => {
    await renderPanel();

    fireEvent.click(batchHead(7));
    expect(await screen.findByText("高级后端工程师（高并发方向）")).toBeInTheDocument();
    expect(screen.getByText("全栈工程师")).toBeInTheDocument();
    // 每条记录都有自己的 详情 / 重投 按钮。
    expect(screen.getAllByRole("button", { name: /详\s*情/ }).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByRole("button", { name: /重投/ }).length).toBeGreaterThanOrEqual(2);

    // 再次点击收起。
    fireEvent.click(batchHead(7));
    expect(screen.queryByText("高级后端工程师（高并发方向）")).not.toBeInTheDocument();
  });

  it("opens the detail Drawer from an expanded row with full failure info including the URL", async () => {
    await renderPanel();
    fireEvent.click(batchHead(7));
    const detailButtons = await screen.findAllByRole("button", { name: /详\s*情/ });
    fireEvent.click(detailButtons[0]);

    const drawer = await screen.findByRole("dialog");
    expect(
      within(drawer).getByText(/失败页面 URL：https:\/\/example\.com\/job\/12345/),
    ).toBeInTheDocument();
    expect(within(drawer).getByText(/批次 #7 · 第 2 次尝试/)).toBeInTheDocument();
  });

  it("does not enable a horizontal scroll bar (no scroll.x on the table)", async () => {
    const { container } = render(
      <AntdApp>
        <ApplyRecordsPanel disabled={false} onRetried={vi.fn()} />
      </AntdApp>,
    );
    await screen.findByTestId("record-batch-7");
    fireEvent.click(batchHead(7));
    await screen.findByText("高级后端工程师（高并发方向）");

    // scroll.x 未设置：AntD 不会渲染横向滚动容器 .ant-table-content（它是 scroll.x 专属）。
    expect(container.querySelector(".ant-table-content")).toBeNull();
    // 纵向滚动容器仍在（scroll.y），列表高度受限、可纵向滚动。
    expect(container.querySelector(".ant-table-body")).not.toBeNull();
  });

  it("shows an empty state when there are no batches", async () => {
    apiMocks.listRecordBatches.mockResolvedValue({ items: [], total: 0 });
    render(
      <AntdApp>
        <ApplyRecordsPanel disabled={false} onRetried={vi.fn()} />
      </AntdApp>,
    );
    expect(await screen.findByText("还没有投递记录")).toBeInTheDocument();
  });
});
