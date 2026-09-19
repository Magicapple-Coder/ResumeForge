/** 模拟面试接口。 */
import type {
  InterviewAnalysis,
  InterviewAnalysisPayload,
  InterviewAnswerResult,
  InterviewBrief,
  InterviewCreatePayload,
  InterviewDetail,
  InterviewOptimizePayload,
  InterviewOptimizeResult,
  InterviewReviewRecord,
  InterviewReviewRecordPayload,
  Material,
  QuestionAnswer,
  QuestionAnswerPayload,
  QuestionBankOut,
  QuestionBankPayload,
  QuestionBankRecord,
  QuestionBankRecordPayload,
} from "../types";
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

/** 生成个性化题库（基础/项目深挖/反问 HR 三类，即时生成不落库）。 */
export function generateQuestionBank(payload: QuestionBankPayload): Promise<QuestionBankOut> {
  return request("/interview/questions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** 输入一道真实问题，分析答题思路。 */
export function analyzeInterviewQuestion(
  payload: InterviewAnalysisPayload,
): Promise<InterviewAnalysis> {
  return request("/interview/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** 为单道题生成详细参考答案（正文 + 要点 + 话术）。 */
export function generateQuestionAnswer(payload: QuestionAnswerPayload): Promise<QuestionAnswer> {
  return request("/interview/questions/answer", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** 把面试暴露的短板与高频追问反向转成简历改写建议（只出建议、不改正文）。 */
export function optimizeResumeFromInterview(
  payload: InterviewOptimizePayload,
): Promise<InterviewOptimizeResult> {
  return request("/interview/optimize-resume", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ===== D5 题库历史 / 面试复盘历史 =====

/** 保存一次生成的题库为历史。 */
export function saveQuestionBank(payload: QuestionBankRecordPayload): Promise<QuestionBankRecord> {
  return request("/interview/question-banks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listQuestionBanks(): Promise<QuestionBankRecord[]> {
  return request("/interview/question-banks");
}

export function getQuestionBank(id: number): Promise<QuestionBankRecord> {
  return request(`/interview/question-banks/${id}`);
}

/** 删除题库历史（软删，彻底删除在回收站）。 */
export function deleteQuestionBank(id: number): Promise<void> {
  return request(`/interview/question-banks/${id}`, { method: "DELETE" });
}

/** 保存一次面试复盘为历史。 */
export function saveReview(payload: InterviewReviewRecordPayload): Promise<InterviewReviewRecord> {
  return request("/interview/reviews", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listReviews(): Promise<InterviewReviewRecord[]> {
  return request("/interview/reviews");
}

export function getReview(id: number): Promise<InterviewReviewRecord> {
  return request(`/interview/reviews/${id}`);
}

/** 删除复盘历史（软删，彻底删除在回收站）。 */
export function deleteReview(id: number): Promise<void> {
  return request(`/interview/reviews/${id}`, { method: "DELETE" });
}
