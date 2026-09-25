import type { ResumeFormatConfig } from "./resumeFormat";

/** 模板市场（后端 ``/api/resumes/templates`` 的 ``market`` 字段，R-19）。 */

export interface TemplateMarketPreset {
  name: string;
  label: string;
  category: string;
  description: string;
  /** 映射到的内置样式模板名。 */
  template: string;
  /** 映射到的格式预设名（内置 FORMAT_PRESETS）。 */
  format_name: string;
  format_config: ResumeFormatConfig;
  /** 建议字号档位。 */
  font_scale: string;
  /** 建议篇幅（A4 页数）。 */
  page_limit: number;
}
