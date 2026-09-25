/** 简历模板工作台接口：自制样式/格式模板的增删改查。 */
import type { ResumeTemplateDetail, ResumeTemplatePayload } from "../types";
import { ApiError, extractError, request } from "./client";

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

/**
 * 导入「目标模板」（图片 / PDF / DOCX）：由模型读出它的版式参数，落成一份格式模板。
 *
 * 走 multipart 而不是 base64 JSON：一份简历 PDF 几 MB，base64 后还要再涨三分之一，
 * 而这条路径本来就不需要 JSON 结构。
 */
export async function importTemplateFromFile(file: File, name = ""): Promise<ResumeTemplateDetail> {
  const formData = new FormData();
  formData.append("file", file);
  if (name.trim()) formData.append("name", name.trim());
  const resp = await fetch("/api/resume-templates/import-from-file", {
    method: "POST",
    body: formData,
  });
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return (await resp.json()) as ResumeTemplateDetail;
}
