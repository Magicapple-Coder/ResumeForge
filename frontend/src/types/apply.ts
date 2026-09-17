/**
 * 「自动采集 + 匹配度分析 + 自动投递」的前端类型镜像。
 *
 * 这里的字符串字面量联合类型与 `backend/app/models/apply.py` 的常量**逐字一致**，
 * 改一处必须同步另一处（设计 §9 ⑨）。界面只读后端返回的 `admission` / `requires_confirm`，
 * **不在这里再判一次准入**——判断的权威只有后端 `admission_of()` 一处。
 */

// ===== ① 匹配状态（五类）=====
export type MatchStatus =
  "matched" | "expression_gap" | "evidence_insufficient" | "real_gap" | "to_confirm";

export type HardGateResult = "met" | "unmet" | "unknown";
export type AdmissionResult = "allow" | "block" | "needs_confirm";

export interface MatchCondition {
  label: string;
  jd_quote: string;
  status: MatchStatus;
  evidence: string;
}

export interface JobMatchResult {
  hard_conditions: MatchCondition[];
  core_abilities: MatchCondition[];
  bonus_items: MatchCondition[];
  hard_gate: HardGateResult;
  admission: AdmissionResult;
  advice: string;
  notes: string[];
}

export interface JobMatchOut {
  id: number;
  job_id: number | null;
  job_title: string;
  company: string;
  result: JobMatchResult;
  hard_gate: HardGateResult;
  requires_confirm: boolean;
  model: string;
  created_at: string;
  updated_at: string;
}

/** 五类状态的中文名与展示色；`admission` 与后端闸门映射一致，仅用于说明，不用于判定。 */
export const MATCH_STATUS_META: Record<
  MatchStatus,
  { label: string; color: string; admission: AdmissionResult }
> = {
  matched: { label: "已匹配", color: "green", admission: "allow" },
  expression_gap: { label: "表达缺口", color: "blue", admission: "allow" },
  evidence_insufficient: { label: "证据不足", color: "orange", admission: "needs_confirm" },
  real_gap: { label: "真实缺口", color: "red", admission: "block" },
  to_confirm: { label: "待确认", color: "gold", admission: "needs_confirm" },
};

export const ADMISSION_META: Record<AdmissionResult, { label: string; color: string }> = {
  allow: { label: "可投递", color: "green" },
  needs_confirm: { label: "需确认", color: "orange" },
  block: { label: "不投", color: "red" },
};

// ===== ② 任务状态机 =====
export type TaskKind = "collect" | "apply";
export type TaskStatus =
  "pending" | "running" | "paused" | "breaker_paused" | "completed" | "stopped" | "failed";
export type TaskItemStatus = "pending" | "running" | "success" | "failed" | "skipped";
export type QueueStatus = "pending" | "skipped" | "done";
export type BrowserState = "stopped" | "starting" | "running" | "unknown";

export const TASK_STATUS_META: Record<TaskStatus, { label: string; color: string }> = {
  pending: { label: "等待中", color: "default" },
  running: { label: "进行中", color: "processing" },
  paused: { label: "已暂停", color: "warning" },
  breaker_paused: { label: "熔断暂停", color: "error" },
  completed: { label: "已完成", color: "success" },
  stopped: { label: "已停止", color: "default" },
  failed: { label: "失败", color: "error" },
};

export const TASK_ITEM_STATUS_META: Record<TaskItemStatus, { label: string; color: string }> = {
  pending: { label: "待投递", color: "default" },
  running: { label: "进行中", color: "processing" },
  success: { label: "成功", color: "success" },
  failed: { label: "失败", color: "error" },
  skipped: { label: "已跳过", color: "default" },
};

export const QUEUE_STATUS_META: Record<QueueStatus, { label: string; color: string }> = {
  pending: { label: "待投递", color: "default" },
  skipped: { label: "已跳过", color: "default" },
  done: { label: "已投递", color: "success" },
};

export const BROWSER_STATE_META: Record<BrowserState, { label: string; color: string }> = {
  stopped: { label: "未启动", color: "default" },
  starting: { label: "启动中", color: "processing" },
  running: { label: "运行中", color: "success" },
  unknown: { label: "状态未知", color: "warning" },
};

// ===== ③ 失败分类（与后端 FAILURE_CATEGORY_LABELS 一致）=====
export const FAILURE_CATEGORIES = [
  "selector_invalid",
  "login_required",
  "captcha_required",
  "greeting_missing",
  "network_timeout",
  "file_upload_failed",
  "unknown",
] as const;

export type FailureCategory = (typeof FAILURE_CATEGORIES)[number];

export const FAILURE_CATEGORY_LABELS: Record<FailureCategory, string> = {
  selector_invalid: "页面结构变化 / 选择器失效",
  login_required: "需要登录",
  captcha_required: "需要验证码或安全验证",
  greeting_missing: "招呼语缺失",
  network_timeout: "网络超时",
  file_upload_failed: "简历上传失败",
  unknown: "未知失败",
};

/** 后端未给出中文说明时（空串 / 未识别值）回退到原始码或占位。 */
export function failureLabel(category: string, fallback = ""): string {
  if (!category) return fallback;
  return FAILURE_CATEGORY_LABELS[category as FailureCategory] ?? category;
}

// ===== ④ 执行步骤 =====
export const STEP_LABELS: Record<string, string> = {
  opening: "打开岗位页",
  filling: "填写表单",
  greeting: "发送招呼语",
  uploading: "上传简历",
  submitting: "提交投递",
  verifying: "确认结果",
  waiting: "岗位间间隔",
  idle: "空闲",
};

export function stepLabel(step: string): string {
  if (!step) return "空闲";
  return STEP_LABELS[step] ?? step;
}

// ===== ⑤ 配置 =====

/**
 * 投递专用浏览器的选择方式。
 * `auto` = 自动（优先 Chrome，未装回退 Edge）；`custom` = 用下面填的自定义路径。
 */
export type BrowserChoice = "auto" | "chrome" | "edge" | "custom";

export const BROWSER_CHOICE_META: Record<BrowserChoice, { label: string; hint: string }> = {
  auto: { label: "自动（优先 Chrome）", hint: "优先用 Chrome；没装 Chrome 时自动回退 Edge。" },
  chrome: { label: "Google Chrome", hint: "只用 Chrome；找不到会明确提示，不会改用别的浏览器。" },
  edge: { label: "Microsoft Edge", hint: "只用 Edge；找不到会明确提示，不会改用别的浏览器。" },
  custom: {
    label: "自定义路径",
    hint: "填写浏览器可执行文件的完整路径（必须真实存在）。",
  },
};

export interface ApplyConfig {
  interval_seconds: number;
  interval_jitter_seconds: number;
  daily_limit: number;
  per_task_limit: number;
  breaker_threshold: number;
  default_greeting: string;
  skip_same_company: boolean;
  confirm_real_gap: boolean;
  browser_port: number;
  /** 投递台使用的浏览器：自动 / Chrome / Edge / 自定义路径。 */
  browser_choice: BrowserChoice;
  /** 自定义浏览器可执行文件的绝对路径，仅 browser_choice=custom 时生效。 */
  browser_path: string;
  /** 当前对接的招聘网站（站点适配器 key），默认取后端注册表里的第一个站点。 */
  site_key: string;
}

export interface ApplyConfigOut extends ApplyConfig {
  defaults: ApplyConfig;
}

export interface CollectConfig {
  keywords: string[];
  city: string;
  salary_min: number | null;
  experience: string;
  education: string;
  per_task_limit: number;
  interval_seconds: number;
  interval_jitter_seconds: number;
}

export interface CollectConfigOut extends CollectConfig {
  defaults: CollectConfig;
}

// ===== ⑥ 浏览器状态 =====
export interface BrowserStatus {
  state: BrowserState;
  port: number;
  profile_dir: string;
  browser_path: string;
  /** 人类可读的浏览器名（Google Chrome / Microsoft Edge / 自定义浏览器）。 */
  browser_name: string;
  /** 启动浏览器时会打开的站点入口地址，也用于「打开招聘网站」按钮。 */
  entry_url: string;
  logged_in_hint: string;
}

// ===== ⑩ 招聘网站（当前站点）=====

/**
 * 一个已注册的招聘网站。
 *
 * **前端不写死站点清单**：这里的字段全部来自后端 `GET /api/apply/sites`。以后后端注册表里
 * 多加一个站点，界面自动跟着多出一个选项，前端一行都不用改。
 */
export interface SiteOption {
  key: string;
  display_name: string;
  host: string;
  entry_url: string;
  supports_collect: boolean;
  supports_apply: boolean;
}

export interface SiteList {
  /** 当前选中的站点 key（对应 ApplyConfig.site_key）。 */
  current: string;
  sites: SiteOption[];
}

/** 按 key 找站点展示名；找不到时回退 key 本身，绝不显示空串。 */
export function siteDisplayName(list: SiteList | undefined, key: string): string {
  const found = list?.sites.find((site) => site.key === key);
  return found?.display_name ?? key;
}

// ===== ⑦ 队列 =====
export interface ApplyQueueItem {
  id: number;
  job_id: number | null;
  job_title: string;
  company: string;
  resume_id: number | null;
  resume_title: string;
  greeting: string;
  sort_order: number;
  status: QueueStatus;
  admission: AdmissionResult | null;
  hard_gate: HardGateResult | null;
  requires_confirm: boolean;
  created_at: string;
  updated_at: string;
}

export interface ApplyQueueAddItem {
  job_id: number;
  resume_id?: number | null;
  greeting?: string;
  confirm_real_gap?: boolean;
  confirm_unanalyzed?: boolean;
}

/** 入队被 409 拦下时后端回传的结构化原因（用于逐条确认）。 */
export interface QueueConflictDetail {
  message: string;
  job_id?: number;
  gaps?: string[];
  unanalyzed?: boolean;
}

// ===== ⑧ 批次与记录 =====
export interface ApplyTask {
  id: number;
  kind: TaskKind;
  status: TaskStatus;
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  skipped: number;
  current_step: string;
  stop_reason: string;
  config: Record<string, unknown>;
  message: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface ApplyTaskItem {
  id: number;
  task_id: number;
  job_id: number | null;
  job_title: string;
  company: string;
  resume_id: number | null;
  resume_title: string;
  greeting: string;
  status: TaskItemStatus;
  failure_category: string;
  failure_detail: string;
  attempt: number;
  sort_order: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface ApplyTaskDetail extends ApplyTask {
  items: ApplyTaskItem[];
}

export interface ApplyRecord {
  id: number;
  task_id: number;
  job_id: number | null;
  job_title: string;
  company: string;
  resume_title: string;
  greeting: string;
  status: TaskItemStatus;
  failure_category: string;
  failure_label: string;
  failure_detail: string;
  attempt: number;
  created_at: string;
  finished_at: string | null;
}

export interface GreetingPreview {
  greeting: string;
  source: "generated" | "queue" | "default";
}
