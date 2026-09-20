/** 版本对比：纯前端、字段级的人性化差异（不依赖后端 diff 接口）。
 *
 * 把两份简历的结构化内容按顶层字段拆成「卡片区块」：只展示有变化的字段，完全一致的
 * 归入可折叠的一组；字符串字段做行内词级高亮，列表字段做条目级 +/- 对照、嵌套对象拆
 * 子字段逐条比较。原始后端源码 diff 作为兜底（见 ResumeFieldDiffView 的「查看原始差异」）。
 *
 * 词级 diff 复刻 services/resume_diff.py 的 _word_pair_diff 语义：按空白切词、以 LCS
 * 求最小编辑脚本，再映射成 added / removed / unchanged 三态 token。
 */
import type { ResumeContent } from "../types/resume";
import type { DiffToken } from "../types/resumeWriting";
import type {
  FieldDiffResult,
  ListItemView,
  ListSectionDiff,
  ModifiedItemDiff,
  SectionDiff,
  StringSectionDiff,
  SubFieldDiff,
} from "../types/resumeFieldDiff";

const PHOTO_PLACEHOLDER = "[图片]";

type RawItem = Record<string, unknown>;

/** 顶层字段 → 中文标签（以 schema 实际字段为准，勿漏）。 */
const FIELD_LABELS: Record<string, string> = {
  name: "姓名",
  photo: "照片",
  gender: "性别",
  birth_year: "出生年份",
  phone: "电话",
  email: "邮箱",
  city: "城市",
  job_intent: "求职意向",
  summary: "个人总结",
  education: "教育经历",
  experience: "工作/实习经历",
  campus_experience: "校园经历",
  projects: "项目经历",
  skills: "专业技能",
  awards: "荣誉奖项",
};

const STRING_FIELDS = [
  "name",
  "photo",
  "gender",
  "birth_year",
  "phone",
  "email",
  "city",
  "job_intent",
  "summary",
];
const LIST_FIELDS = [
  "education",
  "experience",
  "campus_experience",
  "projects",
  "skills",
  "awards",
];

/** 列表条目子字段 → 中文标签。 */
const LIST_SUBFIELD_LABELS: Record<string, Record<string, string>> = {
  education: {
    school: "学校",
    major: "专业",
    degree: "学历",
    start_date: "开始时间",
    end_date: "结束时间",
    gpa: "GPA",
    courses: "核心课程",
    achievements: "成就",
  },
  experience: {
    company: "公司",
    role: "职位",
    start_date: "开始时间",
    end_date: "结束时间",
    description: "工作描述",
  },
  campus_experience: {
    organization: "组织",
    role: "职位",
    start_date: "开始时间",
    end_date: "结束时间",
    description: "经历描述",
  },
  projects: {
    name: "项目名称",
    role: "角色",
    start_date: "开始时间",
    end_date: "结束时间",
    tech_stack: "技术栈",
    description: "项目描述",
    highlights: "项目亮点",
  },
  skills: { name: "技能", level: "熟练度" },
  awards: { name: "奖项", date: "获得时间", description: "奖项描述" },
};

function str(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : String(value);
}

/** 把 base64 照片替换成占位符，避免把一长串乱码展示给用户。 */
function sanitizePhoto(value: unknown): string {
  if (typeof value === "string" && value.startsWith("data:")) return PHOTO_PLACEHOLDER;
  return str(value);
}

/** 列表条目的匹配签名：同名/同校+同专业这类稳定键，用于判断新增/删除/修改。 */
function itemSignature(key: string, item: RawItem): string {
  switch (key) {
    case "education":
      return `${str(item.school)} ${str(item.major)}`;
    case "experience":
      return `${str(item.company)} ${str(item.role)}`;
    case "campus_experience":
      return `${str(item.organization)} ${str(item.role)}`;
    case "projects":
      return str(item.name);
    case "skills":
      return str(item.name);
    case "awards":
      return `${str(item.name)} ${str(item.date)}`;
    default:
      return "";
  }
}

/** 修改条目的标题（展示用）。 */
function itemTitle(key: string, item: RawItem): string {
  switch (key) {
    case "education":
      return `${str(item.school)} · ${str(item.major)}`.trim();
    case "experience":
      return `${str(item.company)} · ${str(item.role)}`.trim();
    case "campus_experience":
      return `${str(item.organization)} · ${str(item.role)}`.trim();
    case "projects":
      return str(item.name);
    case "skills":
      return str(item.name);
    case "awards":
      return `${str(item.name)} · ${str(item.date)}`.trim();
    default:
      return "";
  }
}

// ===== 词级 / 序列级 diff（复刻后端 difflib 行为）=====

interface Opcode {
  type: "equal" | "delete" | "insert";
  i1: number;
  i2: number;
  j1: number;
  j2: number;
}

/** 以 LCS 求最小编辑脚本（equal/delete/insert 三种 opcode，无需 replace）。 */
function sequenceOpcodes<T>(a: T[], b: T[], eq: (x: T, y: T) => boolean): Opcode[] {
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = eq(a[i], b[j]) ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops: Opcode[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (eq(a[i], b[j])) {
      ops.push({ type: "equal", i1: i, i2: i + 1, j1: j, j2: j + 1 });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: "delete", i1: i, i2: i + 1, j1: j, j2: j });
      i++;
    } else {
      ops.push({ type: "insert", i1: i, i2: i, j1: j, j2: j + 1 });
      j++;
    }
  }
  if (i < n) ops.push({ type: "delete", i1: i, i2: n, j1: j, j2: j });
  if (j < m) ops.push({ type: "insert", i1: i, i2: i, j1: j, j2: m });
  return ops;
}

function splitWords(text: string): string[] {
  return text.split(/\s+/).filter((word) => word.length > 0);
}

/** 一对字符串的词级三态 diff，复刻后端 _word_pair_diff。 */
export function wordDiff(
  oldText: string,
  newText: string,
): { oldTokens: DiffToken[]; newTokens: DiffToken[] } {
  const a = splitWords(oldText);
  const b = splitWords(newText);
  const ops = sequenceOpcodes(a, b, (x, y) => x === y);
  const oldTokens: DiffToken[] = [];
  const newTokens: DiffToken[] = [];
  for (const op of ops) {
    if (op.type === "equal") {
      for (let k = op.i1; k < op.i2; k++) oldTokens.push({ type: "unchanged", text: a[k] });
      for (let k = op.j1; k < op.j2; k++) newTokens.push({ type: "unchanged", text: b[k] });
    } else if (op.type === "delete") {
      for (let k = op.i1; k < op.i2; k++) oldTokens.push({ type: "removed", text: a[k] });
    } else {
      for (let k = op.j1; k < op.j2; k++) newTokens.push({ type: "added", text: b[k] });
    }
  }
  return { oldTokens, newTokens };
}

// ===== 字段级对比 =====

function stringFieldDiff(key: string, oldVal: unknown, newVal: unknown): StringSectionDiff | null {
  const oldText = key === "photo" ? sanitizePhoto(oldVal) : str(oldVal);
  const newText = key === "photo" ? sanitizePhoto(newVal) : str(newVal);
  if (oldText === newText) return null;
  const { oldTokens, newTokens } = wordDiff(oldText, newText);
  return { type: "string", key, label: FIELD_LABELS[key], oldText, newText, oldTokens, newTokens };
}

function compareItemSubfields(
  key: string,
  oldItem: RawItem,
  newItem: RawItem,
): { changed: boolean; subfields: SubFieldDiff[] } {
  const labels = LIST_SUBFIELD_LABELS[key] ?? {};
  const subfields: SubFieldDiff[] = [];
  let changed = false;
  const keys = new Set<string>([...Object.keys(oldItem), ...Object.keys(newItem)]);
  for (const sk of keys) {
    const label = labels[sk] ?? sk;
    const ov = oldItem[sk];
    const nv = newItem[sk];
    if (Array.isArray(ov) || Array.isArray(nv)) {
      const oa = Array.isArray(ov) ? (ov as unknown[]) : [];
      const na = Array.isArray(nv) ? (nv as unknown[]) : [];
      const ops = sequenceOpcodes(oa, na, (x, y) => x === y);
      const removedLines: string[] = [];
      const addedLines: string[] = [];
      for (const op of ops) {
        if (op.type === "delete") {
          for (let k = op.i1; k < op.i2; k++) {
            removedLines.push(sanitizePhoto(oa[k]));
            changed = true;
          }
        } else if (op.type === "insert") {
          for (let k = op.j1; k < op.j2; k++) {
            addedLines.push(sanitizePhoto(na[k]));
            changed = true;
          }
        }
      }
      if (removedLines.length > 0 || addedLines.length > 0) {
        subfields.push({ kind: "list", label, removedLines, addedLines });
      }
    } else {
      const ov2 = sanitizePhoto(ov);
      const nv2 = sanitizePhoto(nv);
      if (ov2 !== nv2) {
        const { oldTokens, newTokens } = wordDiff(ov2, nv2);
        subfields.push({ kind: "string", label, oldText: ov2, newText: nv2, oldTokens, newTokens });
        changed = true;
      }
    }
  }
  return { changed, subfields };
}

function renderItem(key: string, item: RawItem): ListItemView {
  const labels = LIST_SUBFIELD_LABELS[key] ?? {};
  const lines: string[] = [];
  for (const sk of Object.keys(item)) {
    const label = labels[sk] ?? sk;
    const v = item[sk];
    if (Array.isArray(v)) {
      const parts = (v as unknown[]).map((x) => sanitizePhoto(x)).filter((s) => s !== "");
      if (parts.length > 0) lines.push(`${label}：${parts.join("、")}`);
    } else {
      const text = sanitizePhoto(v);
      if (text !== "") lines.push(`${label}：${text}`);
    }
  }
  return { title: itemTitle(key, item), lines };
}

function listFieldDiff(key: string, oldList: unknown, newList: unknown): ListSectionDiff | null {
  const base = Array.isArray(oldList) ? (oldList as RawItem[]) : [];
  const against = Array.isArray(newList) ? (newList as RawItem[]) : [];

  const againstByKey = new Map<string, RawItem[]>();
  for (const it of against) {
    const k = itemSignature(key, it);
    const arr = againstByKey.get(k);
    if (arr) arr.push(it);
    else againstByKey.set(k, [it]);
  }

  const removed: ListItemView[] = [];
  const modified: ModifiedItemDiff[] = [];
  const matchedAgainst = new Set<RawItem>();

  for (const it of base) {
    const k = itemSignature(key, it);
    const candidates = againstByKey.get(k);
    const match = candidates?.find((c) => !matchedAgainst.has(c));
    if (match) {
      matchedAgainst.add(match);
      const { changed, subfields } = compareItemSubfields(key, it, match);
      if (changed) modified.push({ key: itemTitle(key, it), subfields });
    } else {
      removed.push(renderItem(key, it));
    }
  }

  const added: ListItemView[] = [];
  for (const it of against) {
    if (!matchedAgainst.has(it)) added.push(renderItem(key, it));
  }

  const unchangedCount = matchedAgainst.size - modified.length;

  if (removed.length === 0 && added.length === 0 && modified.length === 0) return null;

  return {
    type: "list",
    key,
    label: FIELD_LABELS[key],
    removed,
    added,
    modified,
    unchangedCount,
  };
}

/** 计算两份简历的字段级差异，供 ResumeFieldDiffView 渲染。 */
export function computeFieldDiff(
  base: ResumeContent,
  against: ResumeContent,
  baseTitle: string,
  againstTitle: string,
): FieldDiffResult {
  const changed: SectionDiff[] = [];
  const unchangedLabels: string[] = [];
  const baseObj = base as unknown as RawItem;
  const againstObj = against as unknown as RawItem;
  const order = [...STRING_FIELDS, ...LIST_FIELDS];
  for (const key of order) {
    const label = FIELD_LABELS[key];
    if (STRING_FIELDS.includes(key)) {
      const sec = stringFieldDiff(key, baseObj[key], againstObj[key]);
      if (sec) changed.push(sec);
      else unchangedLabels.push(label);
    } else {
      const sec = listFieldDiff(key, baseObj[key], againstObj[key]);
      if (sec) changed.push(sec);
      else unchangedLabels.push(label);
    }
  }
  return { baseTitle, againstTitle, changed, unchangedLabels };
}
