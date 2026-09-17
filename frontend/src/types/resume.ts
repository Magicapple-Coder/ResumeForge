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
  /** 用户自制的样式模板；内置模板为 false。 */
  custom?: boolean;
  id?: number | null;
}

export interface ResumeFontScaleOption {
  name: ResumeFontScale;
  label: string;
  description: string;
}

/** 格式模板的一项可调参数（后端 FORMAT_FIELDS）。 */
export interface ResumeFormatField {
  key: string;
  label: string;
  type: "color" | "number";
  min?: number;
  max?: number;
  step?: number;
  description?: string;
}

export interface ResumeFormatPreset {
  name: string;
  label: string;
  description: string;
  config: Record<string, string | number>;
  custom?: boolean;
  id?: number | null;
}

export interface ResumeTemplateCatalog {
  templates: ResumeTemplateOption[];
  font_scales: ResumeFontScaleOption[];
  /** 格式模板的可调参数清单与内置预设。 */
  format_fields: ResumeFormatField[];
  format_presets: ResumeFormatPreset[];
  /** 三个版式参数的默认值由后端下发，前端不写死——改默认值只改一处。 */
  defaults: {
    template: string;
    font_scale: ResumeFontScale;
    page_limit: number;
    format_name?: string;
  };
  /** 系统里是否找到中文字体：决定「直接下载 PDF」是否可用。 */
  pdf_direct_available: boolean;
}

/**
 * 版式参数：样式模板 + 格式模板 + 页数 + 字号。
 *
 * 拆成"样式"和"格式"两件事：样式决定长什么样（HTML/CSS），格式决定排得多密
 * （行高、页边距、强调色）。用户常常只想换其中一个。
 */
export interface ResumeLayout {
  template: string;
  format_name: string;
  page_limit: ResumePageLimit | number;
  font_scale: ResumeFontScale;
  /**
   * 按简历的版式覆盖。
   *
   * 三态语义，必须区分开：**不传**（undefined）= 这次不涉及、保持原样；
   * **空对象** = 明确清掉覆盖；**有值** = 写入。
   */
  format_config?: ResumeFormatConfig;
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
  /** 格式模板（版式覆盖）名；空串表示用样式模板自带的版式。 */
  format_name: string;
  /**
   * 只属于这份简历的版式覆盖（叠加在 format_name 之上）。
   *
   * 「自动一页」试出来的方案写在这里，而不是去改具名格式模板——那会让所有引用它的
   * 简历一起变，而自动一页的结果只对当前这份内容成立。
   */
  format_config: ResumeFormatConfig;
  page_limit: number;
  font_scale: ResumeFontScale;
  created_at: string;
}

/** 版式覆盖：键取自 `ResumeFormatField.key`，值都是数值（颜色也是十六进制字符串）。 */
export type ResumeFormatConfig = Record<string, number | string>;

/** 「自动一页」用的实测高度，单位随意、只要两者同单位（前端传的是 CSS 像素）。 */
export interface ResumeLayoutMeasure {
  used_height: number;
  page_content_height: number;
  page_limit: number;
}

export type ResumeLayoutStatus =
  "overflow" | "dense" | "healthy" | "sparse" | "too_sparse" | "unknown";

export interface ResumeLayoutSuggestion {
  kind: string;
  title: string;
  detail: string;
}

export interface ResumeLayoutPageFill {
  page: number;
  fill: number;
}

export interface ResumeLayoutDiagnosis {
  status: ResumeLayoutStatus;
  status_label: string;
  summary: string;
  /** 整体填充度（0~1 的小数，可能大于 1 表示溢出）。 */
  fill: number;
  pages_needed: number;
  page_limit: number;
  pages: ResumeLayoutPageFill[];
  suggestions: ResumeLayoutSuggestion[];
}

/** 一档候选版式：把 `css` 注入预览、量一次，够放下就用它。 */
export interface ResumeFitCandidate {
  key: string;
  label: string;
  config: ResumeFormatConfig;
  css: string;
}

export interface ResumeFitRoom {
  has_room: boolean;
  steps: number;
  font_floor_px: number;
  font_adjust_floor: number;
  font_floor_note: string;
}

export interface ResumeLayoutAnalysis {
  diagnosis: ResumeLayoutDiagnosis;
  fit_ladder: ResumeFitCandidate[];
  fit_room: ResumeFitRoom;
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
  format_name: string;
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
