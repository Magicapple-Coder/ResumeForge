/** 模拟面试（后端 /api/interview）。 */
import type { ResumeSuggestion } from "./resume";

export const INTERVIEW_TYPES = [
  "技术面",
  "项目深挖",
  "行为面（STAR）",
  "HR 面",
  "综合面",
  "案例分析",
  "英语面试",
  "压力面",
] as const;

export const INTERVIEW_DIFFICULTIES = ["初级", "中级", "高级"] as const;

export const INTERVIEWER_STYLES = ["严谨专业", "温和引导", "持续追问", "压力质询"] as const;

export type InterviewType = (typeof INTERVIEW_TYPES)[number];
export type InterviewDifficulty = (typeof INTERVIEW_DIFFICULTIES)[number];
export type InterviewerStyle = (typeof INTERVIEWER_STYLES)[number];
export type InterviewStatus = "active" | "finished";

export const MIN_INTERVIEW_ROUNDS = 3;
export const MAX_INTERVIEW_ROUNDS = 12;

export interface InterviewMessage {
  id: number;
  role: "interviewer" | "user" | "note";
  content: string;
  context: {
    index?: number;
    rounds?: number;
    feedback?: string;
    persona?: string;
  };
  status: string;
  error: string;
  created_at: string;
}

export interface InterviewReportDimension {
  name: string;
  score: number;
  comment: string;
}

export interface InterviewReport {
  score?: number;
  dimensions?: InterviewReportDimension[];
  strengths?: string[];
  improvements?: string[];
  summary?: string;
  /** 报告生成失败时后端留下说明，界面按"无报告"处理并展示原因。 */
  error?: boolean;
}

export interface InterviewBrief {
  id: number;
  title: string;
  job_id: number | null;
  job_title: string;
  company: string;
  interview_type: InterviewType | string;
  difficulty: InterviewDifficulty | string;
  interviewer_style: InterviewerStyle | string;
  rounds: number;
  status: InterviewStatus;
  created_at: string;
  updated_at: string;
  answered_rounds: number;
}

export interface InterviewDetail extends InterviewBrief {
  persona: string;
  focus: string;
  model: string;
  report: InterviewReport;
  messages: InterviewMessage[];
}

export interface InterviewCreatePayload {
  title?: string;
  job_id?: number | null;
  interview_type: InterviewType;
  difficulty: InterviewDifficulty;
  interviewer_style: InterviewerStyle;
  rounds: number;
  persona?: string;
  focus?: string;
}

export interface InterviewAnswerResult {
  session: InterviewDetail;
  feedback: string;
  finished: boolean;
}

// ===== R-11 个性化题库 / 答题思路 / 反向优化简历 =====

export const QUESTION_BANK_TYPES = ["基础题", "项目深挖题", "反问HR题"] as const;
export type QuestionBankType = (typeof QUESTION_BANK_TYPES)[number];

export interface InterviewQuestionItem {
  question: string;
  purpose: string;
  answer_hint: string;
}

export interface QuestionBankGroup {
  type: string;
  questions: InterviewQuestionItem[];
}

export interface QuestionBankOut {
  job_id: number | null;
  job_title: string;
  company: string;
  resume_id: number | null;
  groups: QuestionBankGroup[];
  llm_used: boolean;
  notes: string[];
}

export interface QuestionBankPayload {
  job_id?: number | null;
  resume_id?: number | null;
}

export interface InterviewAnalysisPayload {
  question: string;
  job_id?: number | null;
  resume_id?: number | null;
  context?: string;
}

export interface InterviewAnalysis {
  question: string;
  framework: string;
  key_points: string[];
  follow_up: string[];
  pitfalls: string[];
}

export interface QuestionAnswerPayload {
  question: string;
  job_id?: number | null;
  resume_id?: number | null;
}

export interface QuestionAnswer {
  question: string;
  answer: string;
  key_points: string[];
  sample_phrasing: string;
}

export interface InterviewOptimizePayload {
  resume_id: number;
  job_id?: number | null;
  weaknesses?: string[];
  follow_ups?: string[];
}

export interface InterviewOptimizeResult {
  resume_id: number;
  suggestions: ResumeSuggestion[];
  llm_used: boolean;
  notes: string[];
}

// ===== D5 题库历史 / 面试复盘历史 =====

export interface QuestionBankRecord {
  id: number;
  job_id: number | null;
  job_title: string;
  company: string;
  resume_id: number | null;
  resume_title: string;
  groups: QuestionBankGroup[];
  model: string;
  created_at: string;
  updated_at: string;
}

export interface QuestionBankRecordPayload {
  job_id?: number | null;
  job_title?: string;
  company?: string;
  resume_id?: number | null;
  resume_title?: string;
  groups: QuestionBankGroup[];
  model?: string;
}

export interface InterviewReviewRecord {
  id: number;
  job_id: number | null;
  job_title: string;
  company: string;
  resume_id: number | null;
  resume_title: string;
  questions: string[];
  analysis: InterviewAnalysis;
  suggestions: ResumeSuggestion[];
  model: string;
  created_at: string;
  updated_at: string;
}

export interface InterviewReviewRecordPayload {
  job_id?: number | null;
  job_title?: string;
  company?: string;
  resume_id?: number | null;
  resume_title?: string;
  questions: string[];
  analysis: InterviewAnalysis;
  suggestions: ResumeSuggestion[];
  model?: string;
}
