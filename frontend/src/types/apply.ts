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

/** 参考分的单个分项（0-100 分 + 权重 + 一句可读的依据）。 */
export interface MatchScoreDimension {
  key: string;
  label: string;
  score: number;
  weight: number;
  evidence: string;
}

/** 匹配度参考分：0-100 总分 + 5 个分项 + **后端下发的免责文案**。
 *
 * 它是**纯本地规则**算出来的派生值（不调模型）、**不参与投递准入**——能不能投仍只看
 * 五类结论。`disclaimer` 必须原样展示，不要自己改写或省略。
 */
export interface MatchReferenceScore {
  score: number;
  dimensions: MatchScoreDimension[];
  disclaimer: string;
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
  /** 派生值、仅展示、带免责；未分析过时为 null。 */
  reference_score: MatchReferenceScore | null;
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
  "site_unsupported",
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
  site_unsupported: "岗位来源不支持自动投递",
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
  /** 采集结果标注类型（校招/实习/社招）；可空=不限。只入库标注，不参与站点筛选与去重。 */
  job_type: string;
  /**
   * **站点侧筛选项**：`{分组 key: 选项编码}`（如 `{ degree: "203" }`）。
   *
   * 与上面 `salary_min` / `experience` / `education` 的分工：那三个筛的是"你的条件 vs
   * 岗位要求"（"我是本科"），这一份是**招聘网站筛选栏本身**（"岗位要求本科"）。
   * 选项清单由后端从站点读来（见 `CollectFilterOptions`），这里只存用户选中的编码。
   */
  filters: Record<string, string>;
}

export interface CollectConfigOut extends CollectConfig {
  defaults: CollectConfig;
}

/** 筛选项清单的来源：登录会话 / 全网通用 / 内置快照 / 读不到。 */
export type CollectFilterSource = "session" | "public" | "snapshot" | "unavailable";

export interface CollectFilterOption {
  code: string;
  label: string;
  /** 只用于界面分组（行业有 15 个一级分组），其余为空。 */
  group: string;
}

export interface CollectFilterGroup {
  key: string;
  /** 拼进搜索地址的参数名（由后端实测站点得到，前端不该自己拼）。 */
  param: string;
  label: string;
  options: CollectFilterOption[];
  source: CollectFilterSource;
  note: string;
}

export interface CollectFilterOptions {
  site_key: string;
  display_name: string;
  groups: CollectFilterGroup[];
  /** 是否读到了"你这个登录账号可见"的清单；false 表示用的是全网通用清单。 */
  session_read: boolean;
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
  /**
   * 这个浏览器是不是**本次运行**启动的。
   *
   * 为 false 表示它是上一次运行时打开的窗口：`state` 照样是 `running`（调试端口在答，
   * 采集与投递都能用），但「关闭浏览器」关不掉它——进程句柄随后端重启丢了，而应用
   * 只关自己拉起的进程，绝不按 PID 去猜。
   */
  owned: boolean;
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
  /**
   * 这个岗位能不能自动投递：取决于**来源**是否能归属到某个招聘网站，与匹配结论无关。
   *
   * 为 false 时（手动录入、来源与投递链接都指不到站点的岗位）勾选框禁用、也不计入
   * 「待投递」——投递台只能驱动招聘网站上的岗位，强投只会得到一条失败记录。
   *
   * **可选**：缺失按"支持"处理（与后端默认同向），判断写 `=== false`，别写 `!x`。
   */
  apply_supported?: boolean;
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
  /**
   * 岗位来源不是投递台支持的招聘网站。
   *
   * 这一类比 `unanalyzed` / `gaps` 更硬：那两类用户可以显式确认后放行，这一类**确认也没用**
   * ——投递时根本定位不到站点，所以界面只提示、不给"仍然加入"的按钮。
   */
  site_unsupported?: boolean;
  /** 被拦下的岗位（开始投递时可能不止一个）。 */
  job_ids?: number[];
  job_titles?: string[];
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

/**
 * 一个投递批次及其全部记录：投递记录按批次分组展示的载体。
 *
 * 一次「开始投递」= 一个批次；用户一次性投 N 个岗位时，这 N 条记录同属一组。
 * 组头上的统计是该批次自己的账（不随筛选变化），组内是命中的记录。
 */
export interface ApplyRecordBatch {
  id: number;
  status: TaskStatus;
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  skipped: number;
  message: string;
  created_at: string;
  finished_at: string | null;
  items: ApplyRecord[];
}

export interface GreetingPreview {
  greeting: string;
  source: "generated" | "queue" | "default";
}

// ===== ⑫ 站点健康度（degraded 标记）=====

/**
 * 站点健康度状态：`ok` 正常；`degraded` 疑似改版（采集悄悄抓不到东西）。
 *
 * 判据完全在后端（`app/services/site_health.py`）。前端**只读** `status` 与 `reasons`，
 * 绝不在这里再判一次——否则两处判据迟早漂移。
 */
export type SiteHealthStatus = "ok" | "degraded";

/** 一次采集运行的摘要（供界面展开对照「采集记录」）。 */
export interface CollectRunSummary {
  status: string;
  failure_category: string;
  succeeded: number;
  detail_missing: number;
  created_at: string;
}

export interface SiteHealth {
  site_key: string;
  display_name: string;
  status: SiteHealthStatus;
  /** 人类可读、可操作的中文原因（来自后端）。degraded 时非空。 */
  reasons: string[];
  sampled: number;
  selector_failures: number;
  detail_drift_runs: number;
  recent: CollectRunSummary[];
}

export interface SiteHealthList {
  sites: SiteHealth[];
}

/** 取当前站点的健康度；找不到时回退 undefined（前端不自行判定，只如实展示后端结论）。 */
export function siteHealthFor(
  list: SiteHealthList | undefined,
  siteKey: string,
): SiteHealth | undefined {
  return list?.sites.find((site) => site.site_key === siteKey);
}
