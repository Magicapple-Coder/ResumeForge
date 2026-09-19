/** 全局搜索与首页统计。 */
import type { SearchResult, Stats } from "../types";
import { buildQuery, request } from "./client";

export function searchAll(
  q: string,
  scope: "all" | "jobs" | "resumes" | "more" = "all",
): Promise<SearchResult> {
  return request(`/search${buildQuery({ q, scope })}`);
}

export function getStats(): Promise<Stats> {
  return request("/stats");
}
