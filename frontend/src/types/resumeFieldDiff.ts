/** 版本对比：纯前端、字段级的人性化差异结构。
 *
 * ``computeFieldDiff``（见 ``utils/resumeFieldDiff``）把两份简历的结构化内容切成
 * 「区块」：有变化的字段进 ``changed``，完全一致的字段名进 ``unchangedLabels``。
 * 字符串字段做行内词级高亮（复用 ``DiffToken``），列表字段做条目级 +/- 对照。
 */
import type { DiffToken, ResumeDiff } from "./resumeWriting";

/** 字符串子字段（如教育经历条目的「学校」）：旧→新 + 词级高亮。 */
export interface StringSubFieldDiff {
  kind: "string";
  label: string;
  oldText: string;
  newText: string;
  oldTokens: DiffToken[];
  newTokens: DiffToken[];
}

/** 列表子字段（如工作描述的逐条）：删除行红 −、新增行绿 +。 */
export interface ListSubFieldDiff {
  kind: "list";
  label: string;
  removedLines: string[];
  addedLines: string[];
}

export type SubFieldDiff = StringSubFieldDiff | ListSubFieldDiff;

/** 一条「被修改」的列表条目：拆成子字段逐条对照。 */
export interface ModifiedItemDiff {
  key: string;
  subfields: SubFieldDiff[];
}

/** 一条「新增/删除」的列表条目：序列化成可读的 label:value 行。 */
export interface ListItemView {
  title: string;
  lines: string[];
}

export interface StringSectionDiff {
  type: "string";
  key: string;
  label: string;
  oldText: string;
  newText: string;
  oldTokens: DiffToken[];
  newTokens: DiffToken[];
}

export interface ListSectionDiff {
  type: "list";
  key: string;
  label: string;
  removed: ListItemView[];
  added: ListItemView[];
  modified: ModifiedItemDiff[];
  unchangedCount: number;
}

export type SectionDiff = StringSectionDiff | ListSectionDiff;

export interface FieldDiffResult {
  baseTitle: string;
  againstTitle: string;
  changed: SectionDiff[];
  unchangedLabels: string[];
}

/** 默认视图的全部数据：字段级差异 + 后端原始源码 diff（统计与兜底）。 */
export interface DiffViewData {
  raw: ResumeDiff;
  field: FieldDiffResult;
}
