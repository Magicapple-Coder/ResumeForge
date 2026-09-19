/** 备选岗位接口：暂存招聘信息、编辑、按批次挑选后导入岗位广场。 */
import type {
  CandidateJob,
  CandidateJobImportResult,
  CandidateJobPayload,
  CandidateJobUpdatePayload,
} from "../types";
import { buildQuery, request } from "./client";

export function listCandidateJobs(
  params: {
    status?: string;
    keyword?: string;
    /** 只看某一次采集采到的候选（「本次采集结果」）。 */
    collectTaskId?: number;
    limit?: number;
  } = {},
): Promise<CandidateJob[]> {
  const { collectTaskId, ...rest } = params;
  return request(
    `/candidate-jobs${buildQuery({
      ...rest,
      ...(collectTaskId ? { collect_task_id: collectTaskId } : {}),
    })}`,
  );
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

/**
 * 批量导入岗位广场：服务端建岗位并回填关联，**逐条**返回结果。
 *
 * 一次请求而不是逐条调用：勾 10 条要 10 次往返，而且中途失败会留下"导入了一半"的状态。
 */
export function importCandidateJobs(candidateIds: number[]): Promise<CandidateJobImportResult> {
  return request("/candidate-jobs/import", {
    method: "POST",
    body: JSON.stringify({ candidate_ids: candidateIds }),
  });
}

export function deleteCandidateJob(id: number): Promise<void> {
  return request(`/candidate-jobs/${id}`, { method: "DELETE" });
}
