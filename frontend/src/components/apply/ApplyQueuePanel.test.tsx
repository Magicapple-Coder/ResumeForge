/**
 * 投递队列准入徽标的回归测试。
 *
 * 覆盖修复 B：后端可能返回 `admission === null` 且 `requires_confirm === true`（例如匹配分析
 * 结论为空时，"需逐条确认"是后端准入判定的一部分）。此时徽标必须如实展示「需逐条确认」，
 * 不能因为 `admission` 为空就一律显示「未分析」而吞掉这个准入要求。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyQueueItem } from "../../types";
import ApplyQueuePanel from "./ApplyQueuePanel";

const apiMocks = vi.hoisted(() => ({
  listQueue: vi.fn(),
  createApplyTask: vi.fn(),
  reorderQueue: vi.fn(),
  removeQueueItem: vi.fn(),
  updateQueueItem: vi.fn(),
  previewGreeting: vi.fn(),
  listResumes: vi.fn(),
}));

vi.mock("../../api/apply", () => ({
  listQueue: apiMocks.listQueue,
  createApplyTask: apiMocks.createApplyTask,
  reorderQueue: apiMocks.reorderQueue,
  removeQueueItem: apiMocks.removeQueueItem,
  updateQueueItem: apiMocks.updateQueueItem,
  previewGreeting: apiMocks.previewGreeting,
  QueueConflictError: class QueueConflictError extends Error {},
}));

vi.mock("../../api/resumes", () => ({
  listResumes: apiMocks.listResumes,
}));

const BASE_ITEM: ApplyQueueItem = {
  id: 1,
  job_id: 11,
  job_title: "后端开发",
  company: "A公司",
  resume_id: null,
  resume_title: "",
  greeting: "",
  sort_order: 0,
  status: "pending",
  admission: null,
  hard_gate: null,
  requires_confirm: false,
  created_at: "2026-09-17T08:00:00",
  updated_at: "2026-09-17T08:00:00",
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.listQueue.mockResolvedValue([]);
  apiMocks.listResumes.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ApplyQueuePanel 准入徽标", () => {
  it("admission 为空但 requires_confirm 为真时展示「需逐条确认」而非「未分析」", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...BASE_ITEM, admission: null, requires_confirm: true },
    ]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("需逐条确认")).toBeInTheDocument();
    expect(screen.queryByText("未分析")).not.toBeInTheDocument();
  });

  it("admission 为空且无需确认时展示「未分析」", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...BASE_ITEM, admission: null, requires_confirm: false },
    ]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("未分析")).toBeInTheDocument();
    expect(screen.queryByText("需逐条确认")).not.toBeInTheDocument();
  });

  it("有明确结论时保留原徽标，并叠加「需逐条确认」", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...BASE_ITEM, admission: "needs_confirm", requires_confirm: true },
    ]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByText("需确认")).toBeInTheDocument();
    expect(screen.getByText("需逐条确认")).toBeInTheDocument();
  });

  it("队列里没有待投条目时禁用开始投递", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...BASE_ITEM, status: "done" },
      { ...BASE_ITEM, id: 2, job_id: null, job_title: "已删除岗位" },
    ]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    expect(await screen.findByRole("button", { name: /开始投递/ })).toBeDisabled();
  });
});

describe("ApplyQueuePanel 来源闸门", () => {
  const UNSUPPORTED: ApplyQueueItem = {
    ...BASE_ITEM,
    id: 9,
    job_id: 99,
    job_title: "朋友介绍的岗位",
    company: "无",
    apply_supported: false,
  };

  it("来源不支持的条目标出来、勾选框禁用，并在页面上说明怎么处理", async () => {
    apiMocks.listQueue.mockResolvedValue([{ ...BASE_ITEM }, { ...UNSUPPORTED }]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    // 等数据到位：告警出现即代表列表已渲染。
    expect(await screen.findByText(/队列里有 1 个岗位不能用投递台自动投递/)).toBeInTheDocument();
    expect(screen.getByText(/移出队列/)).toBeInTheDocument();

    // 「来源不支持」这个标签在行内，也在告警说明里；这里锁定行上的那一个。
    const row = screen.getByText("朋友介绍的岗位").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("来源不支持")).toBeInTheDocument();

    // 不可勾选：勾了也投不出去，不如一开始就不让选。
    const checkbox = row?.querySelector<HTMLInputElement>('input[type="checkbox"]');
    expect(checkbox).not.toBeNull();
    expect(checkbox?.disabled).toBe(true);
  });

  it("全部来源受支持时不出现这条告警（不误报）", async () => {
    apiMocks.listQueue.mockResolvedValue([{ ...BASE_ITEM }]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    await screen.findByText("后端开发");
    expect(screen.queryByText(/不能用投递台自动投递/)).not.toBeInTheDocument();
    expect(screen.queryByText("来源不支持")).not.toBeInTheDocument();
  });

  it("详情抽屉里说清「能不能自动投递」", async () => {
    apiMocks.listQueue.mockResolvedValue([{ ...UNSUPPORTED }]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /查看队列条目详情/ }));

    expect(await screen.findByText("自动投递")).toBeInTheDocument();
    expect(screen.getByText(/来源不支持：请到原网站自行投递/)).toBeInTheDocument();
  });
});

describe("ApplyQueuePanel 使用指引与详情", () => {
  it("顶部说清岗位从哪来、在队列里做什么、什么时候才真的投出去", async () => {
    apiMocks.listQueue.mockResolvedValue([{ ...BASE_ITEM }]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    const heading = await screen.findByText("队列里放的是「准备投、但还没投」的岗位");
    const flow = heading.closest(".ant-alert");
    expect(flow).not.toBeNull();
    // 入口、准入核对、编辑、以及"不勾选＝整队列投递"这四件事都要写清楚，
    // 用户反馈过"点进来不知道下一步干什么"。
    expect(flow).toHaveTextContent("加入投递台");
    expect(flow).toHaveTextContent("准入结论");
    expect(flow).toHaveTextContent("不勾选＝按顺序投整个队列");
    expect(flow).toHaveTextContent("开始投递");
  });

  it("队列为空时给出可照做的下一步", async () => {
    apiMocks.listQueue.mockResolvedValue([]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    expect(
      await screen.findByText("队列还是空的：先去「岗位广场」挑几个岗位。"),
    ).toBeInTheDocument();
    expect(screen.getByText(/加完之后回到本页/)).toBeInTheDocument();
  });

  it("点岗位名打开详情抽屉（排队序号、使用简历、加入时间）", async () => {
    apiMocks.listQueue.mockResolvedValue([
      { ...BASE_ITEM, greeting: "您好，我想应聘这个岗位", resume_title: "通用版" },
    ]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /查看队列条目详情/ }));

    expect(await screen.findByText("排队序号")).toBeInTheDocument();
    expect(screen.getByText("第 1 位")).toBeInTheDocument();
    expect(screen.getByText("加入队列")).toBeInTheDocument();
    // 「通用版」表格里也显示一份（抽屉与表格各一份）。
    expect(screen.getAllByText("通用版").length).toBeGreaterThan(0);
  });
});

describe("ApplyQueuePanel 右键菜单与操作按钮位置", () => {
  it("右键点击行弹出与「···」一致的菜单（编辑 / 移出队列）", async () => {
    apiMocks.listQueue.mockResolvedValue([{ ...BASE_ITEM }]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    const titleCell = await screen.findByText("后端开发");
    const row = titleCell.closest("tr");
    expect(row).not.toBeNull();

    fireEvent.contextMenu(row as HTMLElement);

    // 右键菜单出现编辑 / 移出队列。
    expect(await screen.findByText("编辑")).toBeInTheDocument();
    expect(screen.getByText("移出队列")).toBeInTheDocument();
  });

  it("操作按钮容器位于最右（flex + justifyContent: flex-end）", async () => {
    apiMocks.listQueue.mockResolvedValue([{ ...BASE_ITEM }]);

    render(
      <AntdApp>
        <ApplyQueuePanel disabled={false} onStarted={vi.fn()} />
      </AntdApp>,
    );

    await screen.findByText("后端开发");
    const actions = document.querySelector(".apply-queue-actions");
    expect(actions).not.toBeNull();
    expect(actions).toHaveStyle({ display: "flex", justifyContent: "flex-end" });
  });
});
