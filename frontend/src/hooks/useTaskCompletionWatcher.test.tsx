/** 任务完成全局监听：transition 语义的守卫——只在"见过进行中 → 消失"时回调。 */
import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTaskCompletionWatcher, WATCH_INTERVAL_MS } from "./useTaskCompletionWatcher";
import type { ApplyTask, ApplyTaskDetail } from "../types";

const apiMocks = vi.hoisted(() => ({
  getCurrentTask: vi.fn(),
  getTaskDetail: vi.fn(),
  getCollectTaskDetail: vi.fn(),
}));

vi.mock("../api/apply", () => ({
  getCurrentTask: apiMocks.getCurrentTask,
  getTaskDetail: apiMocks.getTaskDetail,
  getCollectTaskDetail: apiMocks.getCollectTaskDetail,
}));

function task(overrides: Partial<ApplyTask> = {}): ApplyTask {
  return {
    id: 12,
    kind: "apply",
    status: "running",
    total: 3,
    processed: 1,
    succeeded: 1,
    failed: 0,
    skipped: 0,
    current_step: "opening",
    stop_reason: "",
    config: {},
    message: "",
    started_at: "2026-09-20T12:00:00",
    finished_at: null,
    created_at: "2026-09-20T12:00:00",
    ...overrides,
  };
}

function detail(overrides: Partial<ApplyTaskDetail> = {}): ApplyTaskDetail {
  return { ...task({ status: "completed" }), items: [], ...overrides };
}

/** 让 getCurrentTask 按顺序吐出一系列响应（用完之后重复最后一个）。 */
function queueResponses(...responses: (ApplyTask | null)[]) {
  let index = 0;
  apiMocks.getCurrentTask.mockImplementation(() => {
    const value = responses[Math.min(index, responses.length - 1)];
    index += 1;
    return Promise.resolve(value);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** 推进若干个轮询周期并冲刷微任务。 */
async function advance(cycles: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(WATCH_INTERVAL_MS * cycles + 1);
  });
}

describe("useTaskCompletionWatcher", () => {
  it("fires once when a watched running task disappears (completed)", async () => {
    // tick1：出现并记住；tick2：仍在跑；tick3：消失 → 拉详情 → 回调。
    queueResponses(task(), task(), null);
    apiMocks.getTaskDetail.mockResolvedValue(detail({ id: 12 }));
    const onFinished = vi.fn();

    renderHook(() => useTaskCompletionWatcher(onFinished));
    await advance(1); // tick1 + tick2 边界
    expect(onFinished).not.toHaveBeenCalled();

    await advance(1); // tick3：消失
    expect(onFinished).toHaveBeenCalledTimes(1);
    const event = onFinished.mock.calls[0][0];
    expect(event.detail.id).toBe(12);
    expect(event.detail.status).toBe("completed");

    // 之后不再重复回调。
    await advance(3);
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("does not fire when nothing was watched (app start after task already finished)", async () => {
    queueResponses(null);
    const onFinished = vi.fn();

    renderHook(() => useTaskCompletionWatcher(onFinished));
    await advance(3);
    expect(onFinished).not.toHaveBeenCalled();
    expect(apiMocks.getTaskDetail).not.toHaveBeenCalled();
  });

  it("uses the collect detail endpoint for collect batches", async () => {
    queueResponses(task({ id: 30, kind: "collect" }), null);
    apiMocks.getCollectTaskDetail.mockResolvedValue(
      detail({ id: 30, kind: "collect", succeeded: 5 }),
    );
    const onFinished = vi.fn();

    renderHook(() => useTaskCompletionWatcher(onFinished));
    await advance(1); // tick1 记住 collect 批次；tick2 消失
    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(apiMocks.getCollectTaskDetail).toHaveBeenCalledWith(30);
    expect(apiMocks.getTaskDetail).not.toHaveBeenCalled();
  });

  it("does not fire when the detail fetch fails (no trustworthy terminal state)", async () => {
    queueResponses(task(), null);
    apiMocks.getTaskDetail.mockRejectedValue(new Error("gone"));
    const onFinished = vi.fn();

    renderHook(() => useTaskCompletionWatcher(onFinished));
    await advance(2);
    expect(onFinished).not.toHaveBeenCalled();
  });

  it("renders null as a component (mounted in the layout)", () => {
    queueResponses(null);
    const { container } = render(
      <div data-testid="wrapper">
        <WatchStub />
      </div>,
    );
    expect(container.querySelector("[data-testid=wrapper]")).not.toBeNull();
  });

  function WatchStub() {
    useTaskCompletionWatcher(vi.fn());
    return null;
  }
});
