/** 设置相关接口。 */
import type {
  BackupApplyResult,
  BackupPreview,
  LLMApiKeyRevealResult,
  LLMConfig,
  LLMConfigRecord,
  LLMTestResult,
} from "../types";
import { ApiError, extractError, getFilenameFromDisposition, request } from "./client";

export function getLLMConfig(): Promise<LLMConfig> {
  return request("/settings/llm");
}

export function saveLLMConfig(config: LLMConfig): Promise<LLMConfig> {
  return request("/settings/llm", { method: "PUT", body: JSON.stringify(config) });
}

export function revealLLMApiKey(): Promise<LLMApiKeyRevealResult> {
  return request("/settings/llm/api-key/reveal", { method: "POST" });
}

export function testLLM(config: LLMConfig): Promise<LLMTestResult> {
  return request("/settings/llm/test", { method: "POST", body: JSON.stringify(config) });
}

export function listLLMConfigRecords(): Promise<LLMConfigRecord[]> {
  return request("/settings/llm/records");
}

export function saveLLMConfigRecord(
  record: Pick<LLMConfigRecord, "name"> & LLMConfig,
): Promise<LLMConfigRecord> {
  return request("/settings/llm/records", { method: "POST", body: JSON.stringify(record) });
}

export function deleteLLMConfigRecord(id: number): Promise<void> {
  return request(`/settings/llm/records/${id}`, { method: "DELETE" });
}

/** 导出全部本地数据的备份包（不含大模型 API Key）。 */
export async function exportBackup(): Promise<{ blob: Blob; filename: string }> {
  // 走裸 fetch 而不是 request()：这个响应是二进制压缩包，不是 JSON。
  const resp = await fetch("/api/settings/backup/export");
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return {
    blob: await resp.blob(),
    filename:
      getFilenameFromDisposition(resp.headers.get("Content-Disposition")) ??
      "resumeforge-backup.zip",
  };
}

/** 上传备份包换取预览；裸二进制请求体，不使用 FormData/multipart。 */
export async function uploadBackup(file: File): Promise<BackupPreview> {
  const resp = await fetch("/api/settings/backup/upload", {
    method: "POST",
    // 必须写死 application/zip：浏览器按系统映射给出的 File.type 不可靠，而这个
    // 类型不在 CORS 简单请求允许的范围内，跨站页面无法直接触发恢复流程。
    headers: { "Content-Type": "application/zip" },
    body: file,
  });
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return (await resp.json()) as BackupPreview;
}

/** 用上传阶段返回的 token 确认恢复；会覆盖当前全部数据。 */
export function applyBackup(token: string): Promise<BackupApplyResult> {
  return request("/settings/backup/apply", { method: "POST", body: JSON.stringify({ token }) });
}
