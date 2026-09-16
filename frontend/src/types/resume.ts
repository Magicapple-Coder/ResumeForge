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

/** 字号档位（后端 ResumeFontScale）。 */
export type ResumeFontScale = "small" | "standard" | "large";

/** 最大篇幅：A4 页数，与后端 MAX_RESUME_PAGES 一致。 */
export const RESUME_PAGE_LIMITS = [1, 2, 3] as const;

export type ResumePageLimit = (typeof RESUME_PAGE_LIMITS)[number];

export interface ResumeTemplateOption {
  name: string;
  label: string;
  description: string;
}

export interface ResumeFontScaleOption {
  name: ResumeFontScale;
  label: string;
  description: string;
}

export interface ResumeTemplateCatalog {
  templates: ResumeTemplateOption[];
  font_scales: ResumeFontScaleOption[];
  defaults: { template: string; font_scale: ResumeFontScale };
  /** 系统里是否找到中文字体：决定「直接下载 PDF」是否可用。 */
  pdf_direct_available: boolean;
}

/** 版式参数：模板 + 页数 + 字号，三处（生成、预览、导出）共用。 */
export interface ResumeLayout {
  template: string;
  page_limit: ResumePageLimit | number;
  font_scale: ResumeFontScale;
}

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
  template: string;
  page_limit: number;
  font_scale: ResumeFontScale;
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
  page_limit: number;
  font_scale: ResumeFontScale;
  template: string;
  /** 用户自己补充的生成要求（≤2000 字），作为附加上下文交给模型。 */
  custom_instruction: string;
}

/** 生成接口 SSE 事件（与后端 generator 事件一一对应）。 */
export type StreamEvent =
  | { type: "progress"; message: string }
  | { type: "delta"; text: string }
  | { type: "done"; resume: ResumeContent; warnings: string[] }
  | { type: "saved"; record_id: number }
  | { type: "error"; message: string };
