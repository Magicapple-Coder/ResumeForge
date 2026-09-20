/** 简历相关接口：生成（SSE）、历史、渲染预览、导出下载。 */
import type {
  ExportFormat,
  ExportRequest,
  GenerateOptions,
  Page,
  RedactionOptions,
  ResumeBrief,
  ResumeContent,
  ResumeDetail,
  ResumeFontScale,
  ResumeGenerateTask,
  ResumeLayout,
  ResumeLayoutAnalysis,
  ResumeLayoutMeasure,
  ResumeSuggestions,
  ResumeTemplateCatalog,
  StreamEvent,
} from "../types";
import { ApiError, buildQuery, extractError, getFilenameFromDisposition, request } from "./client";
import { consumeSSE } from "./stream";

export function listResumes(
  params: {
    keyword?: string;
    page?: number;
    page_size?: number;
    job_id?: number;
    favorite?: boolean;
    /** false 只取通用简历（未关联任何岗位） */
    has_job?: boolean;
  } = {},
): Promise<Page<ResumeBrief>> {
  return request(`/resumes${buildQuery(params)}`);
}

/** 只改简历名称，不影响正文与生成告警。 */
export function renameResume(id: number, title: string): Promise<ResumeDetail> {
  return request(`/resumes/${id}`, { method: "PATCH", body: JSON.stringify({ title }) });
}

/** 单独更新简历备注（B5），不触碰正文与版式。 */
export function updateResumeNote(id: number, note: string): Promise<ResumeDetail> {
  return request(`/resumes/${id}/note`, { method: "PATCH", body: JSON.stringify({ note }) });
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

/** 流式生成简历，事件定义见 types/StreamEvent；job_id 为 null 表示生成通用简历。 */
export function generateResume(
  payload: { job_id: number | null; title?: string; options: GenerateOptions },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  // SSE 不经过 request()；这里也必须保留 /api 前缀，才能走 Vite 开发代理。
  return consumeSSE("/api/resumes/generate", payload, onEvent, signal);
}

/** 可选的简历模板与字号档位；顺带告诉前端服务端能否直接生成 PDF。 */
export function fetchResumeTemplates(): Promise<ResumeTemplateCatalog> {
  return request("/resumes/templates");
}

// ===== 后台生成任务（轮询模型，替代弹窗里的同步 SSE 等待）=====
// 生成改成后台任务后，前端流程是：start → 拿到 task_id → 关不关弹窗都轮询 status。
// SSE 的 POST /generate 仍保留，这里只新增一套任务接口，不破坏既有流式语义。

/** 启动一次后台简历生成，返回可轮询的任务；job_id 为 null 表示生成通用简历。 */
export function startResumeGeneration(payload: {
  job_id: number | null;
  title?: string;
  options: GenerateOptions;
}): Promise<ResumeGenerateTask> {
  return request("/resumes/generate/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** 查询一次生成任务的状态（前端 1.5s 轮询）。 */
export function getResumeGenerateTask(taskId: number): Promise<ResumeGenerateTask> {
  return request(`/resumes/generate/tasks/${taskId}`);
}

/** 取消进行中的生成任务；取消后不落库简历，任务标为 cancelled。 */
export function cancelResumeGenerateTask(taskId: number): Promise<ResumeGenerateTask> {
  return request(`/resumes/generate/tasks/${taskId}/cancel`, { method: "POST" });
}

/**
 * 渲染模板预览为 HTML。
 *
 * 传 `html` 时渲染这段（工作台里未保存的编辑内容）；传模板名/格式名时用已保存的
 * 模板；都不传就用内置示例简历内容——新用户没有任何简历记录也能看到效果。
 */
export async function previewResumeTemplate(payload: {
  template_id?: number;
  template_name?: string;
  html?: string;
  format_name?: string;
  format_config?: Record<string, string | number>;
  page_limit?: number;
  font_scale?: ResumeFontScale;
  resume_id?: number;
}): Promise<string> {
  const resp = await fetch("/api/resume-templates/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return resp.text();
}

/** 只调整版式参数（模板/页数/字号），不重新生成内容。 */
export function updateResumeLayout(id: number, layout: ResumeLayout): Promise<ResumeDetail> {
  return request(`/resumes/${id}/layout`, {
    method: "PATCH",
    body: JSON.stringify(layout),
  });
}

/**
 * 版面诊断：把预览里量到的两个高度发过去，拿回结论与逐档收紧方案。
 *
 * 规则全在后端（多少算满、先动哪个旋钮、字号缩到哪为止），前端只负责量准和呈现。
 */
export function analyzeResumeLayout(
  id: number,
  measure: ResumeLayoutMeasure,
): Promise<ResumeLayoutAnalysis> {
  return request(`/resumes/${id}/layout/analyze`, {
    method: "POST",
    body: JSON.stringify({ measure }),
  });
}

/** 渲染简历内容为 HTML（生成完成后、落库前的即时预览） */
export async function renderResume(
  content: ResumeContent,
  layout: Partial<ResumeLayout> = {},
): Promise<string> {
  const resp = await fetch("/api/resumes/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // 后端 ResumeRenderRequest 的结构是 { content, template, page_limit, font_scale }。
    body: JSON.stringify({ content, ...layout }),
  });
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return resp.text();
}

/** 导出为文件（html/md/json/pdf），返回 blob 与服务端建议的文件名 */
export async function exportResume(
  id: number,
  format: ExportFormat,
  /** 为真时跳过"正文还有未完成标记"的拦截，导出一份草稿自查。 */
  allowIncomplete = false,
): Promise<{ blob: Blob; filename: string; pages: number | null; pageLimit: number | null }> {
  const suffix = allowIncomplete ? "&allow_incomplete=true" : "";
  const resp = await fetch(`/api/resumes/${id}/export?format=${format}${suffix}`);
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return {
    blob: await resp.blob(),
    filename:
      getFilenameFromDisposition(resp.headers.get("Content-Disposition")) ?? `resume.${format}`,
    // 只有服务端 PDF 会带这两个头：它用的是自己那套排版，页数可能多于用户选的上限。
    pages: readCountHeader(resp.headers.get("X-Resume-Pages")),
    pageLimit: readCountHeader(resp.headers.get("X-Resume-Page-Limit")),
  };
}

/**
 * 全参数导出（POST 管线）：格式、水印、脱敏、页边距、字号、页数、照片。
 *
 * 与旧 `exportResume` 的 GET 兼容路径不同，这里支持 docx/txt 与全部后处理参数；
 * 「统一导出选项」弹窗走这一条。
 */
export async function exportResumeWithOptions(
  id: number,
  options: ExportRequest,
): Promise<{ blob: Blob; filename: string; pages: number | null; pageLimit: number | null }> {
  const resp = await fetch(`/api/resumes/${id}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return {
    blob: await resp.blob(),
    filename:
      getFilenameFromDisposition(resp.headers.get("Content-Disposition")) ??
      `resume.${options.format}`,
    pages: readCountHeader(resp.headers.get("X-Resume-Pages")),
    pageLimit: readCountHeader(resp.headers.get("X-Resume-Page-Limit")),
  };
}

/** 脱敏预览：返回脱敏后的简历内容，不落库、不改动原记录。 */
export function redactResume(id: number, options: RedactionOptions): Promise<ResumeContent> {
  return request(`/resumes/${id}/redact`, {
    method: "POST",
    body: JSON.stringify(options),
  });
}

/** 头读不到（跨源未放行、或该格式不提供）时返回 null，而不是把 NaN 传下去。 */
function readCountHeader(value: string | null): number | null {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** 读取导出 HTML 文本（用于打开打印窗口生成 PDF） */
export async function fetchResumeHtml(id: number, allowIncomplete = false): Promise<string> {
  const { blob } = await exportResume(id, "html", allowIncomplete);
  return blob.text();
}
