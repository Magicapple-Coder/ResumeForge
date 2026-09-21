/**
 * 任务完成全局监听：投递/采集批次结束后回调——不管用户此刻停在哪个页面。
 *
 * 为什么能"不打断投递"：批次由**后端线程**执行，前端轮询只是看进度，切到其他页面
 * （甚至卸载投递台页面组件）都不会影响执行。本 hook 补的是另一半体验：用户在别的
 * 页面时也能知道"跑完了"。它独立于投递台页面的轮询，挂在全局布局上。
 *
 * 判定语义（transition-based）：只有"本会话里**见过它进行中**、随后不再被报为进行中"
 * 的批次才回调。应用启动时批次早已结束、或接口暂时不可用，都不算——那种情况没有
 * "完成"这个事件可报，也不会误报。
 */
import { useEffect, useRef } from "react";
import { getCurrentTask, getCollectTaskDetail, getTaskDetail } from "../api/apply";
import type { ApplyTask, ApplyTaskDetail } from "../types";

export const WATCH_INTERVAL_MS = 3000;

/** 批次结束后的回调载荷。 */
export interface FinishedTaskEvent {
  detail: ApplyTaskDetail;
}

async function fetchDetailSafe(
  taskId: number,
  kind: ApplyTask["kind"],
): Promise<ApplyTaskDetail | null> {
  try {
    return kind === "collect" ? await getCollectTaskDetail(taskId) : await getTaskDetail(taskId);
  } catch {
    // 批次详情拿不到（不该发生）：没有可信的终态就不回调。
    return null;
  }
}

/**
 * @param onTaskFinished 一个批次从"进行中"变为终态时回调（completed/stopped/failed
 *   都会回调；是否弹窗、弹什么由调用方决定）。
 */
export function useTaskCompletionWatcher(onTaskFinished: (event: FinishedTaskEvent) => void): void {
  // 用 ref 持有最新回调，避免回调身份变化导致轮询重启。
  const callbackRef = useRef(onTaskFinished);
  callbackRef.current = onTaskFinished;
  // 本会话里见过的"进行中"批次（id 与 kind）。它不再被报为进行中时就是完成的时刻。
  const watched = useRef<{ id: number; kind: ApplyTask["kind"] } | null>(null);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const current = await getCurrentTask();
        if (cancelled) return;
        if (current) {
          // 仍在进行中：记住它，等它消失。
          watched.current = { id: current.id, kind: current.kind };
          return;
        }
        const seen = watched.current;
        if (seen == null) return;
        watched.current = null;
        const detail = await fetchDetailSafe(seen.id, seen.kind);
        if (!cancelled && detail) callbackRef.current({ detail });
      } catch {
        /* 接口不可用：静默，下个周期再试。 */
      }
    };

    void tick();
    const timer = window.setInterval(() => void tick(), WATCH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);
}
