/** 自动投递与采集接口封装（`/api/apply`、`/api/collect`）。 */
import type {
  ApplyConfig,
  ApplyConfigOut,
  ApplyQueueAddItem,
  ApplyQueueItem,
  ApplyRecord,
  ApplyRecordBatch,
  ApplyTask,
  ApplyTaskDetail,
  BrowserStatus,
  CollectConfig,
  CollectConfigOut,
  CollectFilterOptions,
  GreetingPreview,
  Page,
  QueueConflictDetail,
  SiteHealthList,
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

/**
 * 当前站点的**站点侧筛选项**清单（求职类型 / 薪资待遇 / 工作经验 / 学历要求 / 公司行业 /
 * 公司规模 / 融资阶段）。
 *
 * 清单由后端从站点自己那里读，**不是前端写死的**：写死的一份在站点改编码之后会静默筛错。
 * 每项带 `source` 说明来源——浏览器在跑就是"你这个账号可见"的完整清单，没跑就是全网通用清单。
 */
export function getCollectFilterOptions(): Promise<CollectFilterOptions> {
  return request("/collect/filters");
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

/**
 * 投递记录按批次分组：一页返回若干批次（默认 5 组），每组带自己的记录。
 * 筛选作用在记录上；分页按批次计。
 */
export function listRecordBatches(params: ApplyRecordParams = {}): Promise<Page<ApplyRecordBatch>> {
  return request(`/apply/records/grouped${buildQuery(params)}`);
}

export function retryRecord(itemId: number): Promise<ApplyTask> {
  return request(`/apply/records/${itemId}/retry`, { method: "POST" });
}

// ===== 采集 =====

/**
 * 开始一次采集。
 *
 * `saveSiteSamples` 为真时保存本次抓到的站点原文（搜索与详情两个接口的响应原文），
 * 供排查解析问题 / 做真实样例回归用。**默认关闭**——往磁盘写站点数据必须由用户每次显式勾选，
 * 且只在不勾选时也保持旧请求形状（不带 `save_site_samples` 字段）。
 */
export function createCollectTask(saveSiteSamples = false): Promise<ApplyTask> {
  const body = saveSiteSamples ? { save_site_samples: true } : {};
  return request("/collect/tasks", { method: "POST", body: JSON.stringify(body) });
}

/**
 * 按岗位 id 只补抓详情（修历史遗留的空 JD）。
 *
 * 与采集共用同一个任务机制：它同样是 `kind=collect` 的批次，进度 / 暂停 / 停止都出现在
 * 「投递台 → 自动采集」的任务面板里，所以调用方必须告诉用户去那里看进度。
 */
export function startBackfill(jobIds: number[]): Promise<ApplyTask> {
  return request("/collect/backfill", {
    method: "POST",
    body: JSON.stringify({ job_ids: jobIds }),
  });
}

export function getCollectTaskDetail(taskId: number): Promise<ApplyTaskDetail> {
  return request(`/collect/tasks/${taskId}`);
}

/**
 * 站点健康度：把"采集悄悄抓不到东西"（站点改版后能翻到列表却读不出岗位/详情）
 * 变成用户看得见的 degraded 标记。判据在后端，前端只展示。
 */
export function getSiteHealth(): Promise<SiteHealthList> {
  return request("/collect/site-health");
}

/**
 * 历史批次列表（按时间倒序）。「采集记录」用它回看每次采集的条件与结果。
 *
 * 采集是个"跑完就看不见过程"的动作：没有这份记录，第二天就不知道上次按什么条件采的、
 * 采到了几条、跳过多少重复。
 */
export function listApplyTasks(
  params: { kind?: "collect" | "apply"; limit?: number } = {},
): Promise<ApplyTask[]> {
  return request(`/apply/tasks${buildQuery(params)}`);
}
