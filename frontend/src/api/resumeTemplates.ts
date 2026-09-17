/** 简历模板工作台接口：自制样式/格式模板的增删改查。 */
import type { ResumeTemplateDetail, ResumeTemplatePayload } from "../types";
import { request } from "./client";

export function listResumeTemplates(kind?: "style" | "format"): Promise<ResumeTemplateDetail[]> {
  return request(`/resume-templates${kind ? `?kind=${kind}` : ""}`);
}

/** 读取内置模板源码，用于「从内置模板复制一份」开始自制。 */
export function fetchBuiltinTemplateSource(
  name: string,
): Promise<{ name: string; label: string; html: string }> {
  return request(`/resume-templates/builtin-source?name=${encodeURIComponent(name)}`);
}

export function fetchResumeTemplate(id: number): Promise<ResumeTemplateDetail> {
  return request(`/resume-templates/${id}`);
}

export function createResumeTemplate(
  payload: ResumeTemplatePayload & { name: string },
): Promise<ResumeTemplateDetail> {
  return request("/resume-templates", { method: "POST", body: JSON.stringify(payload) });
}

export function updateResumeTemplate(
  id: number,
  payload: Partial<ResumeTemplatePayload>,
): Promise<ResumeTemplateDetail> {
  return request(`/resume-templates/${id}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function deleteResumeTemplate(id: number): Promise<void> {
  return request(`/resume-templates/${id}`, { method: "DELETE" });
}
