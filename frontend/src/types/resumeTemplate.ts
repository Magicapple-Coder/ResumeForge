import type { ResumeFormatConfig } from "./resumeFormat";

/** 用户自制简历模板（后端 /api/resume-templates）。 */

export type ResumeTemplateKind = "style" | "format";

export interface ResumeTemplateDetail {
  id: number;
  name: string;
  kind: ResumeTemplateKind;
  description: string;
  enabled: boolean;
  /** 导入时的原始文件名，便于用户认出是哪一版。 */
  source_name: string;
  created_at: string;
  updated_at: string;
  /** 样式模板的 HTML 源码（格式模板为空）。 */
  html: string;
  /** 格式模板的版式覆盖配置（样式模板为空对象）。 */
  config: ResumeFormatConfig;
}

export interface ResumeTemplatePayload {
  /** 新建时必填，修改时选填（改名字要重新做重名检查）。 */
  name?: string;
  kind?: ResumeTemplateKind;
  description?: string;
  html?: string;
  config?: ResumeFormatConfig;
  source_name?: string;
  enabled?: boolean;
}
