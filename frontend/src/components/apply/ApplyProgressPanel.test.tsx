/**
 * 进度面板：条目明细里 `failure_detail` 这个字段**有两种含义**，标签必须跟着状态走。
 *
 * 「按『同公司只投一个岗位』跳过」这类原因也写在这个字段里（后端没有单独的"跳过原因"列）。
 * 如果一律标成「诊断信息」，用户看到跳过条目会以为出错了——而它其实是一次**正常的**跳过。
 */
import { App as AntdApp } from "antd";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ApplyTaskDetail, ApplyTaskItem } from "../../types";
import ApplyProgressPanel from "./ApplyProgressPanel";

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function item(overrides: Partial<ApplyTaskItem>): ApplyTaskItem {
  return {
    id: 1,
    task_id: 1,
    job_id: 10,
    job_title: "后端开发",
    company: "核桃编程",
    resume_id: null,
    resume_title: "",
    greeting: "",
    status: "success",
    failure_category: "",
    failure_detail: "",
    attempt: 1,
    sort_order: 0,
    started_at: "2026-09-21T00:00:00",
    finished_at: "2026-09-21T00:00:05",
    created_at: "2026-09-21T00:00:00",
    ...overrides,
  };
}

function task(items: ApplyTaskItem[]): ApplyTaskDetail {
  return {
    id: 1,
    kind: "apply",
    status: "completed",
    total: items.length,
    processed: items.length,
    succeeded: items.filter((i) => i.status === "success").length,
    failed: 0,
    skipped: items.filter((i) => i.status === "skipped").length,
    current_step: "",
    stop_reason: "done",
    config: {},
    message: "",
    started_at: "2026-09-21T00:00:00",
    finished_at: "2026-09-21T00:01:00",
    created_at: "2026-09-21T00:00:00",
    items,
  };
}

function renderPanel(items: ApplyTaskItem[]) {
  return render(
    <AntdApp>
      <ApplyProgressPanel
        task={task(items)}
        busy={false}
        onPause={() => {}}
        onResume={() => {}}
        onStop={() => {}}
      />
    </AntdApp>,
  );
}

const SKIP_REASON = "按「同公司只投一个岗位」跳过：本批次已经投过「核桃编程」的岗位";

describe("ApplyProgressPanel 条目明细", () => {
  it("跳过的条目标成「跳过原因」，并写明为什么", async () => {
    renderPanel([
      item({ id: 1, status: "success" }),
      item({ id: 2, job_title: "编程讲师", status: "skipped", failure_detail: SKIP_REASON }),
    ]);

    // 展开跳过的那一行看明细。
    const row = await screen.findByText("编程讲师");
    const expand = within(row.closest("tr") as HTMLElement).getByRole("button", {
      name: /展开行|Expand row/i,
    });
    expand.click();

    expect(await screen.findByText("跳过原因")).toBeInTheDocument();
    expect(screen.getByText(SKIP_REASON)).toBeInTheDocument();
    // 「诊断信息」是失败条目的说法，跳过条目不该用它。
    expect(screen.queryByText("诊断信息")).not.toBeInTheDocument();
  });

  it("失败的条目仍然标「诊断信息」——两种含义不能混成一个标签", async () => {
    renderPanel([
      item({ id: 1, job_title: "后端开发", status: "failed", failure_detail: "等聊天输入框超时" }),
    ]);

    const row = await screen.findByText("后端开发");
    within(row.closest("tr") as HTMLElement)
      .getByRole("button", { name: /展开行|Expand row/i })
      .click();

    expect(await screen.findByText("诊断信息")).toBeInTheDocument();
    expect(screen.getByText("等聊天输入框超时")).toBeInTheDocument();
    expect(screen.queryByText("跳过原因")).not.toBeInTheDocument();
  });
});
