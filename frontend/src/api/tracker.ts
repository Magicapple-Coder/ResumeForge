/** 求职进度接口：增删改查、两步导入（解析预览 → 确认写入）与导出。 */
import type {
  Track,
  TrackApplyResult,
  TrackList,
  TrackParseResult,
  TrackPayload,
  TrackRecord,
} from "../types";
import { ApiError, buildQuery, extractError, getFilenameFromDisposition, request } from "./client";

export function listTracks(params: { status?: string; keyword?: string } = {}): Promise<TrackList> {
  return request(`/tracker${buildQuery(params)}`);
}

export function getTrack(id: number): Promise<Track> {
  return request(`/tracker/${id}`);
}

export function createTrack(payload: TrackPayload): Promise<Track> {
  return request("/tracker", { method: "POST", body: JSON.stringify(payload) });
}

export function updateTrack(id: number, payload: TrackPayload): Promise<Track> {
  return request(`/tracker/${id}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function deleteTrack(id: number): Promise<void> {
  return request(`/tracker/${id}`, { method: "DELETE" });
}

export interface TrackParsePayload {
  text: string;
  /** 前端本地读出的图片 data URL 列表（与岗位识别同一条链路）。 */
  images?: { name: string; mime_type: string; data: string }[];
  documents?: { name: string; mime_type: string; data: string }[];
}

/** 解析通知材料，**只返回预览，不写任何数据**。 */
export function parseTracks(payload: TrackParsePayload): Promise<TrackParseResult> {
  return request("/tracker/parse", { method: "POST", body: JSON.stringify(payload) });
}

/** 提交用户确认过的条目；与解析共用同一份合并规则。 */
export function applyTracks(
  items: TrackRecord[],
  source = "recognized",
): Promise<TrackApplyResult> {
  return request("/tracker/apply", {
    method: "POST",
    body: JSON.stringify({ items, source }),
  });
}

/** 导出当前筛选条件下的记录；返回 Blob 与文件名交给下载工具。 */
export async function exportTracks(
  format: "csv" | "json",
  params: { status?: string; keyword?: string } = {},
): Promise<{ blob: Blob; filename: string }> {
  const resp = await fetch(`/api/tracker/export${buildQuery({ ...params, format })}`);
  if (!resp.ok) {
    // 导出走的是原生 fetch（要拿文件流），错误体得自己解——不处理的话用户只会看到
    // "下载了一个内容是一段 JSON 错误的文件"。
    throw new ApiError(await extractError(resp), resp.status);
  }
  const filename =
    getFilenameFromDisposition(resp.headers.get("Content-Disposition")) ?? `求职进度.${format}`;
  return { blob: await resp.blob(), filename };
}
