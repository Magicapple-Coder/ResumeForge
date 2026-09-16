/** 备选岗位接口：暂存招聘信息、编辑与导入标记。 */
import type { CandidateJob, CandidateJobPayload, CandidateJobUpdatePayload } from "../types";
import { buildQuery, request } from "./client";

export function listCandidateJobs(
  params: { status?: string; keyword?: string } = {},
): Promise<CandidateJob[]> {
  return request(`/candidate-jobs${buildQuery(params)}`);
}

export function createCandidateJob(payload: CandidateJobPayload): Promise<CandidateJob> {
  return request("/candidate-jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function getCandidateJob(id: number): Promise<CandidateJob> {
  return request(`/candidate-jobs/${id}`);
}

export function updateCandidateJob(
  id: number,
  payload: CandidateJobUpdatePayload,
): Promise<CandidateJob> {
  return request(`/candidate-jobs/${id}`, { method: "PUT", body: JSON.stringify(payload) });
}

/** 标记为已导入正式岗位（岗位本身仍走正式的岗位保存接口）。 */
export function markCandidateJobImported(id: number, jobId: number): Promise<CandidateJob> {
  return request(`/candidate-jobs/${id}/imported`, {
    method: "POST",
    body: JSON.stringify({ job_id: jobId }),
  });
}

export function deleteCandidateJob(id: number): Promise<void> {
  return request(`/candidate-jobs/${id}`, { method: "DELETE" });
}
