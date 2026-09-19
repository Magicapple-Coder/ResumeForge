/** 岗位相关接口。 */
import type {
  ExtractionDocumentInput,
  ExtractionImageInput,
  Job,
  JobBatchDeleteResult,
  JobBatchStatusResult,
  JobAnalysisResult,
  JobMatchOut,
  JobMatchResult,
  JobPayload,
  Page,
  JobMultiParseResult,
  ParsedJobDraft,
} from "../types";
import { buildQuery, request } from "./client";

export interface JobListParams {
  keyword?: string;
  job_type?: string;
  status?: string;
  favorite?: boolean;
  /** 按录入方式粗筛：`collected`=投递台自动采集，`manual`=其余（手动填写/粘贴/截图/文档等）。 */
  source_kind?: "collected" | "manual";
  page?: number;
  page_size?: number;
}

export function listJobs(params: JobListParams = {}): Promise<Page<Job>> {
  return request(`/jobs${buildQuery(params)}`);
}

export function getJob(id: number): Promise<Job> {
  return request(`/jobs/${id}`);
}

export function createJob(payload: JobPayload): Promise<Job> {
  return request("/jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function updateJob(id: number, payload: Partial<JobPayload>): Promise<Job> {
  return request(`/jobs/${id}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function parseJobText(payload: {
  text: string;
  images?: ExtractionImageInput[];
  documents?: ExtractionDocumentInput[];
}): Promise<ParsedJobDraft> {
  return request("/jobs/parse-text", { method: "POST", body: JSON.stringify(payload) });
}

/**
 * 一次粘贴多份招聘信息：返回一份或多份草稿。
 *
 * 与 `parseJobText` 的差别只在"要不要拆"——单份识别遇到多份材料会合成一份残缺草稿，
 * 所以导入入口统一走这个接口，`items.length === 1` 时退回单份流程即可。
 */
export function parseJobsMultiple(payload: {
  text: string;
  images?: ExtractionImageInput[];
  documents?: ExtractionDocumentInput[];
}): Promise<JobMultiParseResult> {
  return request("/jobs/parse-multiple", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteJob(id: number): Promise<void> {
  return request(`/jobs/${id}`, { method: "DELETE" });
}

export function batchUpdateJobStatus(payload: {
  job_ids: number[];
  status: string;
}): Promise<JobBatchStatusResult> {
  return request("/jobs/batch-status", { method: "POST", body: JSON.stringify(payload) });
}

export function batchDeleteJobs(payload: { job_ids: number[] }): Promise<JobBatchDeleteResult> {
  return request("/jobs/batch-delete", { method: "POST", body: JSON.stringify(payload) });
}

export function generateJobAnalysis(id: number): Promise<JobAnalysisResult> {
  return request(`/jobs/${id}/analysis`, { method: "POST" });
}

/**
 * 岗位匹配度分析：读取个人资料与简历，逐条对照 JD 并落库。
 *
 * 与 `generateJobAnalysis`（岗位需求解读，只读 JD）是两条不同的链路——这里会读取用户资料，
 * 因此生成的是"我够不够"的结论；`force` 为真时忽略已有结论强制重算。
 */
export function generateJobMatch(id: number, force = false): Promise<JobMatchResult> {
  return request(`/jobs/${id}/match-analysis${force ? "?force=true" : ""}`, { method: "POST" });
}

export function getJobMatch(id: number): Promise<JobMatchOut> {
  return request(`/jobs/${id}/match-analysis`);
}

export function deleteJobMatch(id: number): Promise<void> {
  return request(`/jobs/${id}/match-analysis`, { method: "DELETE" });
}
