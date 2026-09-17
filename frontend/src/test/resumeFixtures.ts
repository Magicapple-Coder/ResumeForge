/**
 * 简历版式目录的测试夹具。
 *
 * 形状必须和后端 `GET /api/resumes/templates` 一致（`services/resume_templates.py`）。
 * 放在这里而不是每个测试文件各写一份，是因为这份形状会随功能变——散在各处时，
 * 后端加一个档位就要记得改六份，实际情况是没人记得。
 */

import type { ResumeTemplateCatalog, ResumeLayout } from "../types";

export const TEMPLATE_CATALOG: ResumeTemplateCatalog = {
  templates: [
    { name: "classic", label: "经典", description: "深蓝标题与左侧色条，稳重的通用款式" },
    { name: "modern", label: "现代", description: "青绿配色与圆角标签，适合互联网岗位" },
    { name: "compact", label: "精简", description: "细线分隔、排版紧凑，适合内容多、想压在一页" },
    { name: "elegant", label: "优雅", description: "居中标题与衬线字，留白舒展" },
    { name: "technical", label: "技术", description: "色块标题与等宽辅助信息，信息密度高" },
    { name: "minimal", label: "极简", description: "只用黑灰与字号层级，没有色块与装饰" },
  ],
  font_scales: [
    { name: "small", label: "小字号", description: "字更小、信息密度更高，适合内容偏多" },
    { name: "standard", label: "标准字号", description: "默认档位，兼顾可读性与篇幅" },
    { name: "large", label: "大字号", description: "字更大更醒目，适合内容较少" },
  ],
  format_fields: [
    { key: "accent", label: "强调色", type: "color" },
    { key: "line_height", label: "行高", type: "number", min: 1.2, max: 2.2, step: 0.05 },
  ],
  format_presets: [
    { name: "standard", label: "标准", description: "不改动样式模板自身的版式", config: {} },
    {
      name: "compact",
      label: "紧凑",
      description: "行高与间距收紧、页边距变小，适合想压进一页",
      config: { line_height: 1.45, page_padding: 11, section_gap: 0.85 },
    },
  ],
  defaults: { template: "classic", font_scale: "standard", page_limit: 1, format_name: "" },
  pdf_direct_available: true,
};

export const DEFAULT_LAYOUT: ResumeLayout = {
  template: "classic",
  format_name: "",
  page_limit: 1,
  font_scale: "standard",
};
