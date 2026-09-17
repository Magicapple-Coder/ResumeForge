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
  raw_text: string;
  images: string[];
  note: string;
  source: CandidateJobSource;
  status: CandidateJobStatus;
  imported_job_id: number | null;
  created_at: string;
  updated_at: string;
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
