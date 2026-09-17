/**
 * 对抗性测试：任务轮询在组件卸载后必须停止（避免定时器泄漏与卸载后 setState）。
 *
 * 这是"长任务进度条"最容易出问题的地方：一旦忘了 clearInterval，一个已经离开的页面
 * 会继续每 1.5s 打后端，直到进程结束。
 */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useTaskPolling } from "./useTaskPolling";
import type { ApplyTaskDetail } from "../types";

function makeDetail(status: ApplyTaskDetail["status"]): ApplyTaskDetail {
  return {
    id: 1,
    kind: "apply",
    status,
    total: 3,
    processed: 0,
    succeeded: 0,
    failed: 0,
    skipped: 0,
    current_step: "opening",
    stop_reason: "",
    config: {},
    message: "",
    started_at: null,
    finished_at: null,
    created_at: "2026-09-18T00:00:00",
    items: [],
  };
}

function Harness({
  taskId,
  fetcher,
}: {
  taskId: number | null;
  fetcher: (taskId: number) => Promise<ApplyTaskDetail>;
}) {
  const { detail } = useTaskPolling(fetcher, taskId);
  return <div data-testid="status">{detail?.status ?? "none"}</div>;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useTaskPolling", () => {
  it("stops the interval after unmount so no further requests are made", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => makeDetail("running"));
    const { unmount } = render(<Harness taskId={1} fetcher={fetcher} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    // 轮询确实在推进：再过一个周期应当又拉一次。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(2);

    const callsBeforeUnmount = fetcher.mock.calls.length;
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetcher.mock.calls.length).toBe(callsBeforeUnmount);
  });

  it("stops polling once the task reaches a terminal status", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => makeDetail("completed"));
    render(<Harness taskId={2} fetcher={fetcher} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    // 终态后不再空转。
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not fetch at all when taskId is null", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => makeDetail("running"));
    render(<Harness taskId={null} fetcher={fetcher} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
