/** 面经知识库（后端 /api/interview-experiences）。 */

export const EXPERIENCE_SOURCES = ["self", "peer", "public"] as const;
export type ExperienceSource = (typeof EXPERIENCE_SOURCES)[number];

/** 常见面试轮次（供下拉的白名单参考，存储仍允许自由字符串）。 */
export const EXPERIENCE_ROUND_TYPES = ["一面", "二面", "三面", "HR面", "笔试", "其他"] as const;

export const EXPERIENCE_SOURCE_LABELS: Record<ExperienceSource, string> = {
  self: "自己",
  peer: "同行",
  public: "公开",
};

export interface InterviewExperience {
  id: number;
  title: string;
  company: string;
  position: string;
  job_id: number | null;
  content: string;
  /** 被问到的真实问题清单（R-11 录入，与即时题库互补）。 */
  questions: string[];
  tags: string[];
  source: ExperienceSource | string;
  difficulty: string;
  round_type: string;
  interview_date: string;
  created_at: string;
  updated_at: string;
}

export interface InterviewExperiencePayload {
  title?: string;
  company?: string;
  position?: string;
  job_id?: number | null;
  content?: string;
  questions?: string[];
  tags?: string[];
  source?: ExperienceSource;
  difficulty?: string;
  round_type?: string;
  interview_date?: string;
}
