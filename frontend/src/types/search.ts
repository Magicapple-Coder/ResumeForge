/** 搜索与首页统计类型。 */

import type { Job } from "./job";
import type { ResumeBrief } from "./resume";

/** 全局搜索"更多结果"覆盖的数据域。 */
export type SearchHitType = "referral" | "reminder" | "experience" | "claim" | "material" | "skill";

/** 扩展数据域里的一条命中结果，放在 ``SearchResult.more`` 中。 */
export interface SearchHit {
  type: SearchHitType;
  id: number;
  title: string;
  subtitle: string;
  /** 指向真实前端路由，前端据此跳转。 */
  path: string;
}

export interface SearchResult {
  jobs: Job[];
  resumes: ResumeBrief[];
  /** 内推 / 提醒 / 面经 / 台账 / 资料 / 技能 的命中结果。 */
  more: SearchHit[];
}

/** 待确认的台账条目：首页只报数，点进去才看详情。 */
export interface PendingClaimBrief {
  id: number;
  title: string;
}

/** 最近一条投递成功的记录（岗位可能已被删除，所以带的是快照字段）。 */
export interface LatestApplication {
  id: number;
  job_title: string;
  company: string;
  status: string;
  updated_at: string;
}

export interface Stats {
  job_count: number;
  open_job_count: number;
  resume_count: number;
  week_resume_count: number;
  latest_jobs: Job[];
  latest_resumes: ResumeBrief[];
  // 首页"接下来做什么"的几个数，都只报**待办**。
  favorite_job_count: number;
  pending_claim_count: number;
  pending_claims: PendingClaimBrief[];
  stalled_application_count: number;
  apply_queue_count: number;
  latest_applications: LatestApplication[];
}
