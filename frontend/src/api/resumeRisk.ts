/** 简历风险扫描接口。 */
import type { ResumeRiskScan } from "../types/resumeRisk";
import { request } from "./client";

export function scanResumeRisks(id: number): Promise<ResumeRiskScan> {
  return request(`/resumes/${id}/risk-scan`, { method: "POST" });
}
