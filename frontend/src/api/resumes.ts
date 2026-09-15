/** 简历相关接口：生成（SSE）、历史、渲染预览、导出下载。 */
import type {
  GenerateOptions,
  Page,
  ResumeBrief,
  ResumeContent,
  ResumeDetail,
  ResumeSuggestions,
  StreamEvent,
} from "../types";
import { ApiError, buildQuery, extractError, getFilenameFromDisposition, request } from "./client";
import { consumeSSE } from "./stream";

export type ExportFormat = "json" | "md" | "html";

export function listResumes(
  params: {
    keyword?: string;
    page?: number;
    page_size?: number;
    job_id?: number;
    favorite?: boolean;
  } = {},
): Promise<Page<ResumeBrief>> {
  return request(`/resumes${buildQuery(params)}`);
}

export function getResume(id: number): Promise<ResumeDetail> {
  return request(`/resumes/${id}`);
}

export function deleteResume(id: number): Promise<void> {
  return request(`/resumes/${id}`, { method: "DELETE" });
}

/** 替换一份已保存简历的结构化内容。 */
export function updateResume(id: number, content: ResumeContent): Promise<ResumeDetail> {
  return request(`/resumes/${id}`, { method: "PUT", body: JSON.stringify(content) });
}

/** 单独更新收藏状态，不上传或覆盖简历正文。 */
export function updateResumeFavorite(id: number, favorite: boolean): Promise<ResumeDetail> {
  return request(`/resumes/${id}/favorite`, {
    method: "PATCH",
    body: JSON.stringify({ favorite }),
  });
}

/** 保存用户自行编写的简历，可选关联岗位。 */
export function createManualResume(payload: {
  job_id?: number | null;
  title?: string;
  content: ResumeContent;
}): Promise<ResumeDetail> {
  return request("/resumes/manual", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generateResumeSuggestions(id: number): Promise<ResumeSuggestions> {
  return request(`/resumes/${id}/suggestions`, { method: "POST" });
}

/** 流式生成简历，事件定义见 types/StreamEvent */
export function generateResume(
  payload: { job_id: number; options: GenerateOptions },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  // SSE 不经过 request()；这里也必须保留 /api 前缀，才能走 Vite 开发代理。
  return consumeSSE("/api/resumes/generate", payload, onEvent, signal);
}

/** 渲染简历内容为 HTML（生成完成后、落库前的即时预览） */
export async function renderResume(content: ResumeContent): Promise<string> {
  const resp = await fetch("/api/resumes/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // 后端 ResumeRenderRequest 的结构是 { content: ResumeContent }。
    body: JSON.stringify({ content }),
  });
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return resp.text();
}

/** 导出为文件（html/md/json），返回 blob 与服务端建议的文件名 */
export async function exportResume(
  id: number,
  format: ExportFormat,
): Promise<{ blob: Blob; filename: string }> {
  const resp = await fetch(`/api/resumes/${id}/export?format=${format}`);
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return {
    blob: await resp.blob(),
    filename:
      getFilenameFromDisposition(resp.headers.get("Content-Disposition")) ?? `resume.${format}`,
  };
}

/** 读取导出 HTML 文本（用于打开打印窗口生成 PDF） */
export async function fetchResumeHtml(id: number): Promise<string> {
  const { blob } = await exportResume(id, "html");
  return blob.text();
}
