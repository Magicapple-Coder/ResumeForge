/** 简历内容、生成选项和简历建议类型。 */

export interface ResumeEducation {
  school: string;
  major: string;
  degree: string;
  start_date: string;
  end_date: string;
  gpa: string;
  courses: string[];
  achievements: string[];
}

export interface ResumeExperience {
  company: string;
  role: string;
  start_date: string;
  end_date: string;
  description: string[];
}

export interface ResumeCampusExperience {
  organization: string;
  role: string;
  start_date: string;
  end_date: string;
  description: string[];
}

export interface ResumeProject {
  name: string;
  role: string;
  start_date: string;
  end_date: string;
  tech_stack: string[];
  description: string[];
  highlights: string[];
}

export interface ResumeSkill {
  name: string;
  level: string;
}

export interface ResumeAward {
  name: string;
  date: string;
  description: string;
}

export interface ResumeContent {
  photo: string;
  name: string;
  gender: string;
  birth_year: string;
  phone: string;
  email: string;
  city: string;
  job_intent: string;
  summary: string;
  education: ResumeEducation[];
  experience: ResumeExperience[];
  campus_experience: ResumeCampusExperience[];
  projects: ResumeProject[];
  skills: ResumeSkill[];
  awards: ResumeAward[];
}

export type EnhancementLevel = "light" | "balanced" | "strong";

export interface ResumeBrief {
  id: number;
  title: string;
  job_id: number | null;
  job_title: string;
  company: string;
  source: "ai" | "manual";
  favorite: boolean;
  model: string;
  enhancement_enabled: boolean;
  enhancement_level: EnhancementLevel;
  created_at: string;
}

export interface ResumeDetail extends ResumeBrief {
  content: ResumeContent;
  warnings: string[];
  parse_error: string;
}

export type ResumeSuggestionPriority = "high" | "medium" | "low";

export interface ResumeSuggestion {
  priority: ResumeSuggestionPriority;
  section: string;
  issue: string;
  suggestion: string;
  evidence: string[];
}

export interface ResumeSuggestions {
  job_id: number;
  job_title: string;
  company: string;
  suggestions: ResumeSuggestion[];
}

export interface GenerateOptions {
  enhance: boolean;
  enhancement_level: EnhancementLevel;
}

/** 生成接口 SSE 事件（与后端 generator 事件一一对应）。 */
export type StreamEvent =
  | { type: "progress"; message: string }
  | { type: "delta"; text: string }
  | { type: "done"; resume: ResumeContent; warnings: string[] }
  | { type: "saved"; record_id: number }
  | { type: "error"; message: string };
