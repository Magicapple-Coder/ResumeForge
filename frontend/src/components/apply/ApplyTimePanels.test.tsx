/** 投递台时间显示：后端的无时区时间按 UTC 解释，再转换成浏览器本地时间。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyRecord, ApplyTaskDetail } from "../../types";
import { formatDateTime } from "../../utils/format";
import ApplyProgressPanel from "./ApplyProgressPanel";
import ApplyRecordsPanel from "./ApplyRecordsPanel";

const apiMocks = vi.hoisted(() => ({
  listRecords: vi.fn(),
  retryRecord: vi.fn(),
}));

vi.mock("../../api/apply", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/apply")>();
  return { ...actual, listRecords: apiMocks.listRecords, retryRecord: apiMocks.retryRecord };
});

const STARTED_AT = "2026-09-18T10:00:00";
const FINISHED_AT = "2026-09-18T10:05:00";

function task(): ApplyTaskDetail {
  return {
    id: 7,
    kind: "apply",
    status: "completed",
    total: 1,
    processed: 1,
    succeeded: 1,
    failed: 0,
    skipped: 0,
    current_step: "idle",
    stop_reason: "done",
    config: {},
    message: "投递任务已完成",
    started_at: STARTED_AT,
    finished_at: FINISHED_AT,
    created_at: STARTED_AT,
    items: [
      {
        id: 1,
        task_id: 7,
        job_id: 11,
        job_title: "后端开发",
        company: "示例公司",
        resume_id: null,
        resume_title: "",
        greeting: "您好",
        status: "success",
        failure_category: "",
        failure_detail: "",
        attempt: 1,
        sort_order: 0,
        started_at: STARTED_AT,
        finished_at: FINISHED_AT,
        created_at: STARTED_AT,
      },
    ],
  };
}

function record(): ApplyRecord {
  return {
    id: 1,
    task_id: 7,
    job_id: 11,
    job_title: "后端开发",
    company: "示例公司",
    resume_title: "",
    greeting: "您好",
    status: "success",
    failure_category: "",
    failure_label: "",
    failure_detail: "",
    attempt: 1,
    created_at: STARTED_AT,
    finished_at: FINISHED_AT,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.listRecords.mockResolvedValue({ items: [record()], total: 1 });
});

afterEach(cleanup);

describe("投递台本地时间", () => {
  it("无时区 UTC 与显式 Z 得到相同结果", () => {
    expect(formatDateTime(FINISHED_AT)).toBe(formatDateTime(`${FINISHED_AT}Z`));
  });

  it("投递记录显示转换后的完成时间", async () => {
    render(
      <AntdApp>
        <ApplyRecordsPanel disabled={false} onRetried={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText(formatDateTime(FINISHED_AT))).toBeInTheDocument();
    expect(screen.queryByText(FINISHED_AT)).not.toBeInTheDocument();
  });

  it("执行进度详情显示转换后的开始和结束时间", () => {
    const { container } = render(
      <AntdApp>
        <ApplyProgressPanel
          task={task()}
          busy={false}
          onPause={vi.fn()}
          onResume={vi.fn()}
          onStop={vi.fn()}
        />
      </AntdApp>,
    );

    const expand = container.querySelector<HTMLButtonElement>(".ant-table-row-expand-icon");
    expect(expand).not.toBeNull();
    if (!expand) throw new Error("未找到投递进度的展开按钮");
    fireEvent.click(expand);

    expect(screen.getByText(formatDateTime(STARTED_AT))).toBeInTheDocument();
    expect(screen.getByText(formatDateTime(FINISHED_AT))).toBeInTheDocument();
  });
});
