/** 岗位、岗位解析和岗位分析类型。 */

import type { RecognitionSource, SkillTag } from "./common";

/**
 * 招聘信息的录入方式（后端 `RECOGNITION_SOURCES`）。
 * 保存岗位时会自动写进备注，方便用户回溯这条信息是从哪来的。
 */
export const JOB_RECOGNITION_SOURCES = [
  "手动填写",
  "粘贴文本识别",
  "图片识别",
  "文档识别",
  "备选岗位导入",
  "AI 助手录入",
  "岗位采集",
] as const;

export type JobRecognitionSource = "" | (typeof JOB_RECOGNITION_SOURCES)[number];

export interface Job {
  id: number;
  title: string;
  company: string;
  location: string;
  salary: string;
  job_type: string;
  description: string;
  requirements: string;
  additional_info: string;
  keywords: SkillTag[];
  source: string;
  source_url: string;
  posted_at: string;
  status: string;
  note: string;
  /** 备注里的图片（受限的 base64 data URL，最多 2 张）。 */
  note_images: string[];
  recognition_source: JobRecognitionSource;
  favorite: boolean;
  /**
   * 这个岗位能不能用「投递台」自动投递：来源 / 投递链接必须能归属到某个招聘网站。
   *
   * 由**后端算好下发**（判据在后端只有一处），前端据此禁用「加入投递台」并把原因写在旁边，
   * 而不是让用户点一下才被拒。前端不写死站点名或主机名。
   *
   * **可选**：后端读取接口始终会带这个字段，但缺失时按"支持"处理（与后端 `default=True`
   * 同向）——少一个字段就判成不可投，会把本来能投的岗位藏起来。所以判断一律写
   * `job.apply_supported === false`，不要写 `!job.apply_supported`。
   */
  apply_supported?: boolean;
  created_at: string;
  updated_at: string;
}

/** 一次粘贴里含多份招聘信息时的解析结果；只有一个元素表示没识别出多份。 */
export interface JobMultiParseResult {
  items: ParsedJobDraft[];
  parse_engine: RecognitionSource;
  warnings: string[];
}

export interface JobPayload {
  title: string;
  company?: string;
  location?: string;
  salary?: string;
  job_type?: string;
  description?: string;
  requirements?: string;
  additional_info?: string;
  source_url?: string;
  posted_at?: string;
  status?: string;
  note?: string;
  note_images?: string[];
  recognition_source?: JobRecognitionSource;
  favorite?: boolean;
}

/** 备选岗位：还没核对的招聘信息暂存。 */
export type CandidateJobStatus = "pending" | "imported";

export const CANDIDATE_JOB_SOURCE_LABELS = [
  "手动添加",
  "粘贴文本",
  "招聘截图",
  "招聘文档",
] as const;

export type CandidateJobSource = (typeof CANDIDATE_JOB_SOURCE_LABELS)[number] | "助手录入";

export interface CandidateJob {
  id: number;
  title: string;
  company: string;
  /** 采集多带出来的两个字段；手动粘贴的候选为空串。 */
  location: string;
  salary: string;
  raw_text: string;
  images: string[];
  note: string;
  /**
   * 来源。手动录入的是 `CANDIDATE_JOB_SOURCE_LABELS` 里的那几种；**投递台采集进来的是
   * 站点名**（由后端站点注册表给出，前端不写死具体名字），所以读取侧不能收窄成枚举——
   * 收窄会让后端多注册一个站点就把界面类型检查搞红。
   */
  source: string;
  /** 采集带回来的 JD 两段（已在服务端按小标题切好）；手动粘贴的候选为空串。 */
  description: string;
  requirements: string;
  /** 原始岗位链接（采集来的才有）：界面上用它显示「回原站看」。 */
  source_url: string;
  /** 产生这条候选的采集批次；为空表示不是采集来的。 */
  collect_task_id: number | null;
  status: CandidateJobStatus;
  imported_job_id: number | null;
  created_at: string;
  updated_at: string;
}

export type CandidateJobImportOutcomeKind =
  "imported" | "duplicate" | "trashed" | "invalid" | "missing";

/** 单条候选的导入结果：**逐条**反馈，用户才知道是哪几条没进去、为什么。 */
export interface CandidateJobImportOutcome {
  candidate_id: number;
  title: string;
  outcome: CandidateJobImportOutcomeKind;
  job_id?: number | null;
}

export interface CandidateJobImportResult {
  imported: number;
  duplicate: number;
  /** 岗位广场的回收站里已有同名岗位：既没新建也没恢复，等你去回收站处理。 */
  trashed: number;
  invalid: number;
  missing: number;
  results: CandidateJobImportOutcome[];
}

export interface CandidateJobPayload {
  title?: string;
  company?: string;
  raw_text?: string;
  images?: string[];
  note?: string;
  source?: CandidateJobSource;
}

export interface CandidateJobUpdatePayload {
  title?: string;
  company?: string;
  raw_text?: string;
  images?: string[];
  note?: string;
}

export interface ParsedJobDraft extends Required<
  Omit<JobPayload, "note" | "favorite" | "note_images" | "recognition_source">
> {
  warnings: string[];
  /**
   * 识别引擎（模型还是本地规则）。与 `Job.recognition_source`（招聘信息的**录入方式**）
   * 是两件事：这里只说明这次识别是谁做的，保存岗位时的来源由输入类型决定。
   */
  parse_engine: RecognitionSource;
  /** 图片识别时模型逐字抄录的原文；纯文本识别为空。 */
  recognized_text: string;
}

export interface JobBatchStatusResult {
  updated: number;
}

export interface JobBatchDeleteResult {
  deleted: number;
}

export type JobAnalysisPriority = "high" | "medium" | "low";

export interface JobRequirementAnalysis {
  priority: JobAnalysisPriority;
  category: string;
  requirement: string;
  evidence: string;
}

export interface JobSearchAdvice {
  title: string;
  action: string;
  rationale: string;
}

export interface JobAnalysisResult {
  summary: string;
  requirements: JobRequirementAnalysis[];
  advice: JobSearchAdvice[];
}
