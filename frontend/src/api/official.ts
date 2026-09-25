/** 官网岗位采集接口。 */
import type {
  OfficialProbeResult,
  OfficialRun,
  OfficialRunDetail,
  OfficialSite,
  OfficialSitePayload,
} from "../types";
import { buildQuery, request } from "./client";

const BASE = "/official";

export function listOfficialSites(options: { enabledOnly?: boolean } = {}) {
  return request<OfficialSite[]>(
    `${BASE}/sites${buildQuery({ enabled_only: options.enabledOnly ? "true" : "" })}`,
  );
}

/**
 * 新建一个源并**立刻探测**（后端在同一次请求里完成）。
 *
 * 探测失败**不是**异常：被阻断、未识别都会正常返回一个结果对象，`state` 说明是哪种。
 * 所以这里不 try/catch，由调用方按 `state` 决定怎么提示。
 */
export function createOfficialSite(payload: OfficialSitePayload) {
  return request<OfficialProbeResult>(`${BASE}/sites`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateOfficialSite(siteId: number, payload: OfficialSitePayload) {
  return request<OfficialProbeResult>(`${BASE}/sites/${siteId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function reprobeOfficialSite(siteId: number) {
  return request<OfficialProbeResult>(`${BASE}/sites/${siteId}/probe`, { method: "POST" });
}

export function deleteOfficialSite(siteId: number) {
  return request<void>(`${BASE}/sites/${siteId}`, { method: "DELETE" });
}

/**
 * 采一次。
 *
 * robots 拒绝、被站点阻断都**不是** HTTP 错误——后端返回 200 + 一条带结论的运行记录。
 * 只有"没识别出系统""记录不存在"这类用户操作问题才会抛 ApiError。
 *
 * `maxJobs` 是**这一次**的条数上限（不填 = 不设）：岗位上万条的站点一次翻不完，
 * 而用户多半只想先看前几十条。它只管这一趟，不存进站点。
 */
export function collectOfficialSite(siteId: number, maxJobs?: number, jobKeywords?: string) {
  const body = {
    ...(maxJobs ? { max_jobs: maxJobs } : {}),
    ...(jobKeywords?.trim() ? { job_keywords: jobKeywords.trim() } : {}),
  };
  return request<OfficialRun>(`${BASE}/sites/${siteId}/collect`, {
    method: "POST",
    // 没有任何临时参数时**不发请求体**，与加这个参数之前完全一样。
    body: Object.keys(body).length > 0 ? JSON.stringify(body) : undefined,
  });
}

export function listOfficialRuns(options: { siteId?: number; limit?: number } = {}) {
  return request<OfficialRun[]>(
    `${BASE}/runs${buildQuery({ site_id: options.siteId, limit: options.limit })}`,
  );
}

export function getOfficialRun(runId: number) {
  return request<OfficialRunDetail>(`${BASE}/runs/${runId}`);
}

/**
 * 核实这次采集的待核实地址，并据此重算结论。
 *
 * **这是把「无法确认」变成硬结论的唯一途径**：那些地址里既有真漏掉的，也有早就招满、链接还
 * 留在地图里的——逐个访问才能分清。后端一次最多核实 20 个（对站点的礼貌约束），返回重算后的
 * 运行记录。
 */
export function verifyOfficialRun(runId: number) {
  return request<OfficialRunDetail>(`${BASE}/runs/${runId}/verify`, { method: "POST" });
}

/**
 * 请求停止一次采集。
 *
 * **不是强杀**：采集器在下一个检查点（每条岗位之间）自己停下来，因此已抓到的岗位与账目都是
 * 完整的，照常给出对账结论。
 */
export function stopOfficialRun(runId: number) {
  return request<OfficialRun>(`${BASE}/runs/${runId}/stop`, { method: "POST" });
}
