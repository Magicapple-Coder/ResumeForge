/** 搜索与首页统计类型。 */

import type { Job } from "./job";
import type { ResumeBrief } from "./resume";

export interface SearchResult {
  jobs: Job[];
  resumes: ResumeBrief[];
}

export interface Stats {
  job_count: number;
  open_job_count: number;
  resume_count: number;
  week_resume_count: number;
  latest_jobs: Job[];
  latest_resumes: ResumeBrief[];
}
