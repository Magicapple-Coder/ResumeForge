/** 版式覆盖的类型定义，单独成文件是为了避免 `resume.ts` ↔ `templateMarket.ts`
 *  互相引用（resume.ts 已经引用了 TemplateMarketPreset）。
 *
 *  键取自 `ResumeFormatField.key`，值都是数值（颜色也是十六进制字符串）。
 *  例外是 `section_order`：它是一串分区键，不是 CSS 数值（见 utils/resumeSectionOrder.ts）。 */
export type ResumeFormatConfig = Record<string, number | string | string[]>;
