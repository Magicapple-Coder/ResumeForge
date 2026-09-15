/** 岗位、岗位解析和岗位分析类型。 */

import type { SkillTag } from "./common";

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
  favorite: boolean;
  created_at: string;
  updated_at: string;
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
  favorite?: boolean;
}

export interface ParsedJobDraft extends Required<Omit<JobPayload, "note" | "favorite">> {
  warnings: string[];
  recognition_source: "ai" | "local";
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
