/**
 * 任务进度轮询：按固定间隔拉取批次详情，任务进入终态后自动停下。
 *
 * 为什么是轮询而不是 SSE：这是单用户本地应用，一次任务最多几百个岗位、间隔以秒计，
 * 轮询（1.5s）实现简单、断线自愈，成本可忽略；设计也明确采用轮询模型（§4.2）。
 */
import { DependencyList, useCallback, useEffect, useRef, useState } from "react";
import type { ApplyTaskDetail, TaskStatus } from "../types";

/** 仍在推进的状态：只有这些状态下才需要继续轮询。 */
export const ACTIVE_TASK_STATUSES: readonly TaskStatus[] = [
  "pending",
  "running",
  "paused",
  "breaker_paused",
];

export function isActiveTaskStatus(status: TaskStatus): boolean {
  return ACTIVE_TASK_STATUSES.includes(status);
}

const POLL_INTERVAL_MS = 1500;

interface TaskPollingState {
  detail: ApplyTaskDetail | null;
  error: string;
  refresh: () => Promise<void>;
  setDetail: (detail: ApplyTaskDetail | null) => void;
}

/**
 * @param fetcher 拉取指定批次详情；对同一 `taskId` 应保持稳定语义（内部用 ref 取最新引用）。
 * @param taskId  要轮询的批次 id；为 `null` 时清空并停止。
 */
export function useTaskPolling(
  fetcher: (taskId: number) => Promise<ApplyTaskDetail>,
  taskId: number | null,
  deps: DependencyList = [],
): TaskPollingState {
  const [detail, setDetail] = useState<ApplyTaskDetail | null>(null);
  const [error, setError] = useState("");
  const version = useRef(0);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    if (taskId == null) return;
    const current = ++version.current;
    try {
      const result = await fetcherRef.current(taskId);
      if (current === version.current) {
        setDetail(result);
        setError("");
      }
    } catch (err) {
      if (current === version.current) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 依赖由调用方通过 deps 控制
  }, [taskId, ...deps]);

  // 切换任务时清空旧详情，避免把上一个任务的状态显示成新任务的。
  useEffect(() => {
    version.current += 1;
    setDetail(null);
    setError("");
    if (taskId != null) void refresh();
  }, [taskId, refresh]);

  // 仅在任务仍处于推进状态时轮询；进入终态后自动停止，避免空转。
  useEffect(() => {
    if (taskId == null) return;
    const status = detail?.status;
    if (status && !isActiveTaskStatus(status)) return;
    const timer = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [taskId, detail?.status, refresh]);

  return {
    detail,
    error,
    refresh,
    setDetail: (next) => {
      version.current += 1;
      setDetail(next);
    },
  };
}
