/** 岗位相关接口。 */
import type {
  Job,
  JobBatchDeleteResult,
  JobBatchStatusResult,
  JobPayload,
  Page,
  ParsedJobDraft,
} from "../types";
import { buildQuery, request } from "./client";

export interface JobListParams {
  keyword?: string;
  job_type?: string;
  status?: string;
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

export function parseJobText(payload: { text: string }): Promise<ParsedJobDraft> {
  return request("/jobs/parse-text", { method: "POST", body: JSON.stringify(payload) });
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
