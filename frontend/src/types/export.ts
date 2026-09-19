/** 多格式导出与脱敏的类型（R-16 / R-17）。枚举字符串与后端逐字一致。 */
import type { ResumeFontScale } from "./resume";

/** 导出格式（与后端 ``ExportFormat`` 逐字一致）。 */
export type ExportFormat = "json" | "md" | "html" | "pdf" | "docx" | "txt";

/** 脱敏范围（与后端 ``RedactionOptions`` 逐字一致）。 */
export interface RedactionOptions {
  mask_name: boolean;
  mask_phone: boolean;
  mask_email: boolean;
  mask_company: boolean;
  mask_school: boolean;
  mask_project: boolean;
  mask_product: boolean;
}

/** 全参数导出请求体（与后端 ``ExportRequest`` 逐字一致）。 */
export interface ExportRequest {
  format: ExportFormat;
  watermark?: string;
  redact?: boolean;
  redact_options?: RedactionOptions;
  /** 页边距（mm）；null 表示沿用记录里存的值。 */
  margin_mm?: number | null;
  font_scale?: ResumeFontScale | null;
  page_limit?: number | null;
  include_photo?: boolean;
  allow_incomplete?: boolean;
}

/** 导出结果（对应一个 blob + 服务端建议文件名 + 页数元数据）。 */
export interface ExportResult {
  blob: Blob;
  filename: string;
  pages: number | null;
  pageLimit: number | null;
}

/** 可选的导出格式（顺序即「导出选项」里的展示顺序）。 */
export const EXPORT_FORMATS: { value: ExportFormat; label: string }[] = [
  { value: "pdf", label: "PDF" },
  { value: "docx", label: "Word" },
  { value: "html", label: "HTML" },
  { value: "md", label: "Markdown" },
  { value: "txt", label: "纯文本" },
  { value: "json", label: "JSON" },
];

/** 脱敏范围的可配置项（与后端字段一一对应，label 用于勾选界面）。 */
export const REDACTION_FIELDS: { key: keyof RedactionOptions; label: string }[] = [
  { key: "mask_name", label: "姓名" },
  { key: "mask_phone", label: "手机" },
  { key: "mask_email", label: "邮箱" },
  { key: "mask_company", label: "公司" },
  { key: "mask_school", label: "学校" },
  { key: "mask_project", label: "项目" },
  { key: "mask_product", label: "产品名（正文）" },
];

/** 默认遮罩可直接识别身份的四项（与后端默认值一致）。 */
export const DEFAULT_REDACTION_OPTIONS: RedactionOptions = {
  mask_name: true,
  mask_phone: true,
  mask_email: true,
  mask_company: true,
  mask_school: false,
  mask_project: false,
  mask_product: false,
};
