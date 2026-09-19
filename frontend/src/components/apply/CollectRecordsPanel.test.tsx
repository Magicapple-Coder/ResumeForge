/**
 * 「采集记录」摘要行：搜索采集与「补齐详情」是两种口径，不能混。
 *
 * 两者都是 `kind=collect`、都会出现在这份记录里。若按同一套搜索口径渲染，补详情批次会显示成
 * 「已暂存 0 个」「采集条件：关键词：xxx」——两个字段对它都没有意义，纯误导。这里钉住两种口径
 * 各自正确，且互不串味。
 */
import { App as AntdApp } from "antd";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyTask } from "../../types";
import CollectRecordsPanel from "./CollectRecordsPanel";

const apiMocks = vi.hoisted(() => ({ listApplyTasks: vi.fn() }));

vi.mock("../../api/apply", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/apply")>();
  return { ...actual, listApplyTasks: apiMocks.listApplyTasks };
});

// 展开后的「本次采集结果」会自己去拉候选接口；这里只想验摘要行，替换掉它。
vi.mock("./CollectResultPanel", () => ({ default: () => null }));

const BACKFILL_MESSAGE =
  "已为 1 条岗位补齐职位描述。另有 1 条跳过（已有描述 / 仍然抓不到 / 已在回收站里）。";

function task(overrides: Partial<ApplyTask> = {}): ApplyTask {
  return {
    id: 1,
    kind: "collect",
    status: "completed",
    total: 3,
    processed: 3,
    succeeded: 3,
    failed: 0,
    skipped: 2,
    current_step: "idle",
    stop_reason: "done",
    config: { keywords: ["后端"], city: "北京" },
    message: "采集完成：已暂存 3 个岗位。",
    started_at: null,
    finished_at: "2026-09-18T10:05:00",
    created_at: "2026-09-18T10:00:00",
    ...overrides,
  };
}

function renderPanel() {
  return render(
    <AntdApp>
      <CollectRecordsPanel />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.listApplyTasks.mockReset();
});

afterEach(cleanup);

describe("CollectRecordsPanel", () => {
  it("搜索批次照旧显示关键词/城市与已暂存条数", async () => {
    apiMocks.listApplyTasks.mockResolvedValue([task()]);
    renderPanel();

    expect(await screen.findByText("已暂存 3 个，重复 2 个")).toBeInTheDocument();
    expect(screen.getByText("关键词：后端；城市：北京")).toBeInTheDocument();
  });

  it("搜索批次没有条件时显示占位文案，不会渲染成空行", async () => {
    // conditionText 对搜索批次永远给一句可读文案（真条件，或"（未记录采集条件）"），
    // 因此 `{condition && <Text/>}` 不会漏出一个空节点、摘要行也不会被多余分隔符撕开。
    apiMocks.listApplyTasks.mockResolvedValue([
      task({ config: {}, succeeded: 1, skipped: 0, message: "采集完成：已暂存 1 个岗位。" }),
    ]);
    renderPanel();

    expect(await screen.findByText("（未记录采集条件）")).toBeInTheDocument();
    // 摘要行仍在同一标签里：占位与结果之间没有被断成空行。
    expect(screen.getByText("已暂存 1 个")).toBeInTheDocument();
  });

  it("补详情批次不显示「已暂存」和采集条件，改用后端文案", async () => {
    apiMocks.listApplyTasks.mockResolvedValue([
      task({
        id: 9,
        total: 2,
        processed: 2,
        succeeded: 2,
        skipped: 1,
        // 补详情的 config 里确实带着已保存的采集配置（keywords/city），但显示时不该拿它当"条件"。
        config: {
          keywords: ["测试关键词"],
          city: "上海",
          backfill_job_ids: [1, 2],
          backfilled: 1,
          backfill_skipped: 1,
        },
        message: BACKFILL_MESSAGE,
      }),
    ]);
    renderPanel();

    // 后端文案被直接采用（不另造一套措辞）。
    expect((await screen.findAllByText(BACKFILL_MESSAGE)).length).toBeGreaterThan(0);
    // 搜索口径的摘要与"采集条件"都不能出现。
    expect(screen.queryByText(/已暂存/)).not.toBeInTheDocument();
    expect(screen.queryByText(/测试关键词/)).not.toBeInTheDocument();
    expect(screen.queryByText(/上海/)).not.toBeInTheDocument();
  });

  it("补详情批次 message 为空时按 task.succeeded/skipped 兜底，不读 config 的账目", async () => {
    // 模拟「用户中途停止」：停止路径不写 message、run() 的收尾（写 config.backfilled /
    // backfill_skipped）也没执行，所以 config 里**只有** backfill_job_ids。此时若兜底去读
    // config.backfilled，会拿到 undefined→0，显示成「已补齐 0 条」（其实已补好 5 条）。
    // 只有 succeeded/skipped 是逐条同步、停止时也正确的数据源。
    apiMocks.listApplyTasks.mockResolvedValue([
      task({
        id: 11,
        status: "stopped",
        total: 7,
        processed: 7,
        succeeded: 5,
        skipped: 2,
        failed: 0,
        config: { backfill_job_ids: [1, 2, 3] },
        message: "",
      }),
    ]);
    renderPanel();

    expect(await screen.findByText(/已补齐 5 条/)).toBeInTheDocument();
    expect(screen.getByText(/跳过 2 条/)).toBeInTheDocument();
    // 关键回归判据：绝不能出现从 config 读出的 0，也不能串成搜索口径的「已暂存」。
    expect(screen.queryByText(/已补齐 0 条/)).not.toBeInTheDocument();
    expect(screen.queryByText(/已暂存/)).not.toBeInTheDocument();
  });
});
