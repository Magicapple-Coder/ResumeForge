/** 求职数据看板（后端 /api/analytics）。 */

export interface FunnelStage {
  status: string;
  label: string;
  count: number;
}

export interface TrendPoint {
  /** YYYY-MM。 */
  month: string;
  /** 面向展示的短标签，如 "9月"。 */
  label: string;
  count: number;
}

export interface AnalyticsDashboard {
  total_applications: number;
  valid_applications: number;
  interview_count: number;
  interview_rate: number;
  assessment_count: number;
  assessment_to_interview_count: number;
  assessment_pass_rate: number;
  offer_count: number;
  funnel: FunnelStage[];
  trend: TrendPoint[];
}
