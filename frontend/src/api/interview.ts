/** 模拟面试接口。 */
import type {
  InterviewAnswerResult,
  InterviewBrief,
  InterviewCreatePayload,
  InterviewDetail,
} from "../types";
import type { Material } from "../types";
import { request } from "./client";

export function listInterviews(limit = 50): Promise<InterviewBrief[]> {
  return request(`/interview?limit=${limit}`);
}

export function getInterview(id: number): Promise<InterviewDetail> {
  return request(`/interview/${id}`);
}

/** 开一场面试；后端会同时生成第一个问题。 */
export function createInterview(payload: InterviewCreatePayload): Promise<InterviewDetail> {
  return request("/interview", { method: "POST", body: JSON.stringify(payload) });
}

/** 提交一轮回答：返回点评与下一题；满轮次时 finished 为真并且已带报告。 */
export function submitInterviewAnswer(id: number, content: string): Promise<InterviewAnswerResult> {
  return request(`/interview/${id}/answers`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

/** 提前结束并出报告。 */
export function finishInterview(id: number): Promise<InterviewDetail> {
  return request(`/interview/${id}/finish`, { method: "POST" });
}

export function deleteInterview(id: number): Promise<void> {
  return request(`/interview/${id}`, { method: "DELETE" });
}

/** 把这场面试的记录与报告存进资料箱（面试复盘）。 */
export function interviewToMaterial(id: number): Promise<Material> {
  return request(`/interview/${id}/to-material`, { method: "POST" });
}
