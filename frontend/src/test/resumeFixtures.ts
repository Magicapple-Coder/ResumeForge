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
  ],
  font_scales: [
    { name: "small", label: "小字号", description: "字更小、信息密度更高，适合内容偏多" },
    { name: "standard", label: "标准字号", description: "默认档位，兼顾可读性与篇幅" },
    { name: "large", label: "大字号", description: "字更大更醒目，适合内容较少" },
  ],
  defaults: { template: "classic", font_scale: "standard" },
  pdf_direct_available: true,
};

export const DEFAULT_LAYOUT: ResumeLayout = {
  template: "classic",
  page_limit: 1,
  font_scale: "standard",
};
