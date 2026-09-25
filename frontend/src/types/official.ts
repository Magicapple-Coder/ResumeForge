/**
 * 官网岗位采集的类型。
 *
 * 枚举值（`verdict` / `status` / `blocks`）与后端的字面量**逐字一致**，中文标签由后端一并
 * 返回（`*_label` 字段）。前端**不自己维护一份映射**——两份映射迟早漂移，而漂移的表现是
 * 某个状态在界面上显示成原始英文，排查时没人会想到去比对两边。
 */

/** 一个公司官网源。 */
export interface OfficialSite {
  id: number;
  company: string;
  homepage_url: string;
  careers_url: string;
  /** 识别出的招聘系统标识；空串 = 未识别。 */
  source_kind: string;
  /** 系统展示名；未识别时为空串。 */
  source_label: string;
  endpoint: string;
  confidence: string;
  confidence_label: string;
  /** 判断依据的说明，直接展示（"为什么认为这家公司用的是这套系统"）。 */
  probe_evidence: string;
  /** robots 结论；null = 还没查过。 */
  robots_allowed: boolean | null;
  robots_detail: string;
  crawl_delay_seconds: number | null;
  min_interval_seconds: number;
  enabled: boolean;
  last_probed_at: string | null;
  created_at: string;
  latest_verdict: string;
  latest_verdict_label: string;
  latest_headline: string;
  /** 最近一次运行的 id；还没采过时为 null。 */
  latest_run_id: number | null;
  /** 最近一次运行的**状态**（running / done / stopped / failed）。 */
  latest_status: string;
  latest_status_label: string;
  /** 现在能不能采集，由服务端判定；前端只读，不二次判断。 */
  can_collect: boolean;
}

/** 一次采集的账目与对账结论。 */
export interface OfficialRun {
  id: number;
  site_id: number;
  site_company: string;
  status: string;
  status_label: string;
  pages: number;
  /** 去重后的取回条数；对总数比的是它。 */
  collected: number;
  stored: number;
  skipped: number;
  detail_missing: number;
  total_hint: number | null;
  verdict: string;
  verdict_label: string;
  evidence: string;
  /** 一句话结论，直接展示。 */
  headline: string;
  /** 已确认的差额条数。 */
  missing: number;
  blocks: string[];
  block_labels: string[];
  started_at: string;
  finished_at: string | null;
  error: string;
  /**
   * 这次采集花掉的模型调用次数。
   *
   * **用户自付 key，这一项必须可见**——否则他只能去翻服务商的账单才知道这个功能用了他多少钱。
   */
  llm_calls: number;
}

/**
 * 这次采集**每一页是怎么读出来的**。
 *
 * 它不是对账依据，而是花销与可复现性的说明：哪几页动了模型、配方有没有归纳成功、下次还需不需要
 * 再花钱。`methods` 是逐页的句子，由后端写好，界面原样展示。
 */
export interface OfficialExtraction {
  methods: string[];
  llm_calls: number;
  /** 本次归纳并成功存下的配方数。存下来之后，同一站点的后续采集不再需要模型。 */
  recipes_learned: number;
  /**
   * 因为超过层级上限而没有跟进的地址数。
   *
   * **它不改变结论**（站点的次级导航不是岗位），但报告里要能回答"为什么这次只翻了这么几页"。
   */
  deep_links_skipped: number;
}

/** 对账报告的一层依据。 */
export interface ReconcileLayer {
  layer: string;
  label: string;
  detail: string;
}

export interface ReconcileDetail {
  basis?: string;
  layers?: ReconcileLayer[];
  termination?: { state: string; detail: string } | null;
  stopped_reason?: string;
  /** 本次临时岗位筛选；空表示没有筛选。 */
  job_filter?: string;
  /** 历史报告里的岗位快照，避免候选后来变化后报告失去可读性。 */
  collected_jobs?: OfficialCollectedJob[];
  robots?: { allowed: boolean; detail: string };
  /**
   * 待核实地址：站点地图里有、这次没抓到的岗位页。
   *
   * **不是"漏抓清单"**——里面既有真漏的，也有早就招满、URL 还留在地图里的历史岗位。
   * 逐个点开看一眼才能分清，所以界面上要把这句话说在前面，不能让用户以为点一遍就对了。
   */
  candidates?: string[];
  /** 逐条核实的结果（点过「核实这些地址」之后才有）。 */
  verifications?: VerificationEntry[];
}

export interface OfficialCollectedJob {
  candidate_id: number | null;
  job_id: number | null;
  title: string;
  company: string;
  location: string;
  source_url: string;
}

/** 一条存活校验的结果。 */
export interface VerificationEntry {
  url: string;
  /** `live` 仍在招 / `gone` 已下架 / `unknown` 判不出来。 */
  state: string;
  /** 中文说明，由后端给出——前端不自己维护枚举映射。 */
  label: string;
  detail: string;
}

/**
 * 这次采集与这家公司近期基线的偏离。
 *
 * **它不是一条对账依据**，而是一个独立提醒：条数下降既可能是我们漏抓，也可能是这家公司真的
 * 关掉了那些岗位——只看条数分不出来，所以 `detail` 里必须把这句话说清楚。
 */
export interface OfficialTrend {
  /** stable / dropped / jumped / insufficient / unmeasured。 */
  state: string;
  /** 中文说明，由后端给出——前端不自己维护枚举映射。 */
  label: string;
  detail: string;
  /** 基线（历史中位数）与本次条数；历史不足时为 null。 */
  baseline: number | null;
  latest: number;
}

/** 报告页用：带上逐层依据、趋势提醒与抽取方式。 */
export interface OfficialRunDetail extends OfficialRun {
  reconcile_detail: ReconcileDetail;
  trend?: OfficialTrend | null;
  extraction: OfficialExtraction;
}

/** 探测时试过的一个端点。 */
export interface OfficialProbeAttempt {
  feed_key: string;
  endpoint: string;
  block: string;
  block_label: string;
  job_count: number;
  detail: string;
}

/**
 * 一次探测的结果。
 *
 * `state` 是三态（命中 / 未识别 / 被阻断），**不是布尔**：把"被阻断"混进"未识别"会让人以为
 * 这家公司不用这套系统，而实际上我们只是没看到内容。
 */
export interface OfficialProbeResult {
  state: string;
  state_label: string;
  site: OfficialSite;
  job_count: number;
  evidence: string;
  attempts: OfficialProbeAttempt[];
}

export interface OfficialSitePayload {
  company: string;
  homepage_url?: string;
  careers_url?: string;
}

/**
/** 采集结论 → 展示用的语义色。**只影响颜色，不影响措辞**（措辞全部来自后端）。 */
export const VERDICT_COLORS: Record<string, string> = {
  complete: "success",
  incomplete: "warning",
  unknown: "default",
};
