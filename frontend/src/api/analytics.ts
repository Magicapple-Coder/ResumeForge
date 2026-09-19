/** 求职数据看板接口。 */
import type { AnalyticsDashboard } from "../types";
import { buildQuery, request } from "./client";

export function getAnalyticsDashboard(trendMonths: number = 6): Promise<AnalyticsDashboard> {
  return request(`/analytics/dashboard${buildQuery({ trend_months: trendMonths })}`);
}
