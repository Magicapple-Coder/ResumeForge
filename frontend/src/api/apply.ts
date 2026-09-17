/** 自动投递与采集接口封装（`/api/apply`、`/api/collect`）。 */
import type {
  ApplyConfig,
  ApplyConfigOut,
  ApplyQueueAddItem,
  ApplyQueueItem,
  ApplyRecord,
  ApplyTask,
  ApplyTaskDetail,
  BrowserStatus,
  CollectConfig,
  CollectConfigOut,
  GreetingPreview,
  Page,
  QueueConflictDetail,
  SiteList,
} from "../types";
import { ApiError, buildQuery, extractError, request } from "./client";

// ===== 配置 =====

export function getApplyConfig(): Promise<ApplyConfigOut> {
  return request("/apply/config");
}

export function updateApplyConfig(payload: ApplyConfig): Promise<ApplyConfigOut> {
  return request("/apply/config", { method: "PUT", body: JSON.stringify(payload) });
}

export function getCollectConfig(): Promise<CollectConfigOut> {
  return request("/collect/config");
}

export function updateCollectConfig(payload: CollectConfig): Promise<CollectConfigOut> {
  return request("/collect/config", { method: "PUT", body: JSON.stringify(payload) });
}

// ===== 招聘网站（当前站点）=====

/** 已注册的招聘网站 + 当前选中项。界面据此展示当前站点，不写死站点名。 */
export function listSites(): Promise<SiteList> {
  return request("/apply/sites");
}

// ===== 投递专用浏览器 =====

export function getBrowserStatus(): Promise<BrowserStatus> {
  return request("/apply/browser/status");
}

export function startBrowser(): Promise<BrowserStatus> {
  return request("/apply/browser/start", { method: "POST" });
}

/** 在已启动的专用浏览器里重新打开招聘网站入口（标签页被关掉或跳走后使用）。 */
export function openBrowserSite(): Promise<BrowserStatus> {
  return request("/apply/browser/open", { method: "POST" });
}

export function stopBrowser(): Promise<void> {
  return request("/apply/browser/stop", { method: "POST" });
}

// ===== 队列 =====

export function listQueue(): Promise<ApplyQueueItem[]> {
  return request("/apply/queue");
}

/**
 * 入队被准入闸门拦下时抛出：`detail` 是后端给出的结构化原因。
 *
 * 用自定义错误而不是普通 `ApiError`，是因为界面要据此决定**弹哪种确认**——
 * "未分析"和"真实缺口"是两种不同的确认，需要拿到 `unanalyzed` / `gaps` 才能分辨。
 * 普通 `ApiError` 只保留一句文本，会把这两种情况混成一个笼统的 409。
 */
export class QueueConflictError extends Error {
  constructor(public detail: QueueConflictDetail) {
    super(detail.message);
    this.name = "QueueConflictError";
  }
}

export async function addToQueue(items: ApplyQueueAddItem[]): Promise<ApplyQueueItem[]> {
  const resp = await fetch("/api/apply/queue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (resp.status === 409) {
    const body = (await resp.json().catch(() => null)) as { detail?: QueueConflictDetail } | null;
    const detail = body?.detail;
    if (detail && typeof detail === "object") throw new QueueConflictError(detail);
  }
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return (await resp.json()) as ApplyQueueItem[];
}

export function reorderQueue(order: number[]): Promise<ApplyQueueItem[]> {
  return request("/apply/queue/reorder", { method: "PATCH", body: JSON.stringify({ order }) });
}

export function updateQueueItem(
  itemId: number,
  payload: { greeting?: string; resume_id?: number },
): Promise<ApplyQueueItem> {
  return request(`/apply/queue/${itemId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function removeQueueItem(itemId: number): Promise<void> {
  return request(`/apply/queue/${itemId}`, { method: "DELETE" });
}

/** 按岗位生成一版招呼语（不落库）；给了 item_id 就基于队列里的当前值。 */
export function previewGreeting(payload: {
  job_id: number;
  item_id?: number;
}): Promise<GreetingPreview> {
  return request("/apply/greeting/preview", { method: "POST", body: JSON.stringify(payload) });
}

// ===== 执行批次（轮询模型）=====

export function createApplyTask(payload: {
  job_ids?: number[];
  use_queue: boolean;
}): Promise<ApplyTask> {
  return request("/apply/tasks", { method: "POST", body: JSON.stringify(payload) });
}

export function getCurrentTask(): Promise<ApplyTask | null> {
  return request("/apply/tasks/current");
}

export function getTaskDetail(taskId: number): Promise<ApplyTaskDetail> {
  return request(`/apply/tasks/${taskId}`);
}

export function pauseTask(taskId: number): Promise<ApplyTask> {
  return request(`/apply/tasks/${taskId}/pause`, { method: "POST" });
}

export function resumeTask(taskId: number): Promise<ApplyTask> {
  return request(`/apply/tasks/${taskId}/resume`, { method: "POST" });
}

export function stopTask(taskId: number): Promise<ApplyTask> {
  return request(`/apply/tasks/${taskId}/stop`, { method: "POST" });
}

// ===== 记录 =====

export interface ApplyRecordParams {
  keyword?: string;
  result?: string;
  page?: number;
  page_size?: number;
}

export function listRecords(params: ApplyRecordParams = {}): Promise<Page<ApplyRecord>> {
  return request(`/apply/records${buildQuery(params)}`);
}

export function retryRecord(itemId: number): Promise<ApplyTask> {
  return request(`/apply/records/${itemId}/retry`, { method: "POST" });
}

// ===== 采集 =====

export function createCollectTask(): Promise<ApplyTask> {
  return request("/collect/tasks", { method: "POST" });
}

export function getCollectTaskDetail(taskId: number): Promise<ApplyTaskDetail> {
  return request(`/collect/tasks/${taskId}`);
}
