/**
 * 简历字段路径的读写与中文说明——与预览里的 `data-resume-path` 同一套写法。
 *
 * 为什么需要它：预览里"点中的那一栏"是一个路径（``summary`` / ``projects.0.description.1``），
 * 而编辑器里的表单字段是另一个形状（列表要点在表单里是一个多行文本框、对应整个数组）。
 * 用路径把 AI 返回的文本写回**内容对象**，比换算成表单字段名再拼数组可靠得多，
 * 也不会因为编辑器换了控件形状而失效。
 *
 * 与后端 `services/resume/resume_field_rewrite.py` 的解析规则一致（那是一份 Python 实现）：
 * 能改的路径集合两边必须相同，否则会出现"前端让改、后端说指不到"。
 */
import type { ResumeContent } from "../types";

/** 在简历里是"若干条要点"的字段（与后端 resume_field_rewrite 的 _LIST_FIELD_LABELS 一致）。 */
const LINE_FIELDS = new Set(["description", "highlights", "achievements", "courses", "tech_stack"]);

const SECTION_LABELS: Record<string, string> = {
  education: "教育经历",
  experience: "实习/工作经历",
  campus_experience: "校园经历",
  projects: "项目经历",
  skills: "专业技能",
  awards: "荣誉奖项",
};

const ITEM_IDENTITY: Record<string, string> = {
  education: "school",
  experience: "company",
  campus_experience: "organization",
  projects: "name",
  skills: "name",
  awards: "name",
};

const LIST_FIELD_LABELS: Record<string, string> = {
  description: "要点",
  highlights: "亮点",
  achievements: "成果",
  courses: "课程",
  tech_stack: "技术栈",
};

const SCALAR_FIELD_LABELS: Record<string, string> = {
  name: "姓名",
  gender: "性别",
  birth_year: "出生年份",
  phone: "电话",
  email: "邮箱",
  city: "城市",
  job_intent: "求职意向",
  summary: "个人总结",
};

const ITEM_SCALAR_LABELS: Record<string, string> = {
  school: "学校",
  major: "专业",
  degree: "学历",
  start_date: "开始时间",
  end_date: "结束时间",
  gpa: "绩点/排名",
  company: "公司",
  role: "角色",
  organization: "组织",
  name: "名称",
  date: "时间",
};

/** 把路径拆成 `(string | number)[]`；非法路径返回空数组。 */
export function parseResumeFieldPath(path: string): (string | number)[] {
  return (path ?? "")
    .split(".")
    .filter((part) => part !== "")
    .map((part) => (/^\d+$/.test(part) ? Number(part) : part));
}

/**
 * 读出路径指向的值（可能是字符串，也可能是数组——编辑器里列表字段是一个整体）。
 *
 * 接受 `string` 路径或已经拆好的段数组：编辑器的表单字段名就是段数组，用它读回来
 * 才能保证"读的"和"写的"是同一个位置。
 */
export function readResumeValueByPath(
  content: ResumeContent | null,
  path: string | (string | number)[],
): unknown {
  if (!content) return undefined;
  const segments = Array.isArray(path) ? path : parseResumeFieldPath(path);
  let current: unknown = content;
  for (const segment of segments) {
    if (current === null || current === undefined) return undefined;
    current = (current as Record<string | number, unknown>)[segment];
  }
  return current;
}

/** 读出路径指向的那一栏的文本；指不到（或不是文本）时返回空串。 */
export function readResumeFieldByPath(content: ResumeContent | null, path: string): string {
  const value = readResumeValueByPath(content, path);
  return typeof value === "string" ? value : "";
}

/**
 * 把任意值写回路径（字符串、字符串数组都行），返回**新的**内容对象。
 *
 * 「整段重写」要写回的是一个数组（一段经历的多条要点），所以这里不能只收字符串。
 */
export function writeResumeValueByPath(
  content: ResumeContent,
  path: string,
  value: unknown,
): ResumeContent {
  const segments = parseResumeFieldPath(path);
  if (segments.length === 0) return content;

  const cloneAt = (node: unknown, depth: number): unknown => {
    if (depth >= segments.length) return value;
    const key = segments[depth];
    if (node === null || node === undefined) return node;
    if (!(key in (node as object))) return node;
    if (Array.isArray(node)) {
      const next = [...node];
      next[key as number] = cloneAt(node[key as number], depth + 1);
      return next;
    }
    if (typeof node === "object") {
      const record = node as Record<string | number, unknown>;
      return { ...record, [key]: cloneAt(record[key], depth + 1) };
    }
    return node;
  };

  return cloneAt(content, 0) as ResumeContent;
}

/** 分成若干条要点的那一栏（一段经历的工作内容、项目亮点……）。 */
export function isLineListPath(path: string): boolean {
  const segments = parseResumeFieldPath(path);
  return segments.length === 3 && LINE_FIELDS.has(String(segments[2]));
}

/** 把某条要点（`experience.0.description.1`）收敛成它所属的那一段（`experience.0.description`）。 */
export function toWholeSegmentPath(path: string): string {
  const segments = parseResumeFieldPath(path);
  if (segments.length === 4 && LINE_FIELDS.has(String(segments[2]))) {
    return `${segments[0]}.${segments[1]}.${segments[2]}`;
  }
  return path;
}

/** 读出某一栏的所有要点；不是列表时返回空数组。 */
export function readResumeLinesByPath(content: ResumeContent | null, path: string): string[] {
  const value = readResumeValueByPath(content, path);
  if (!Array.isArray(value)) return [];
  return value.map((line) => String(line ?? ""));
}

/**
 * 把一段文本写回路径（`writeResumeValueByPath` 的字符串版）。
 *
 * 只复制路径经过的那几个分支，其余保持引用——这样 React 侧只重渲染真正变了的部分，
 * 也避免因为整体深拷贝而丢掉未在表单里呈现的字段。
 */
export function writeResumeFieldByPath(
  content: ResumeContent,
  path: string,
  value: string,
): ResumeContent {
  return writeResumeValueByPath(content, path, value);
}

/** 人话说明"这是哪一栏"，用于弹窗标题与错误提示。 */
export function describeResumeFieldPath(path: string, content?: ResumeContent | null): string {
  const segments = parseResumeFieldPath(path);
  if (segments.length === 0) return "未指定";
  const head = String(segments[0]);
  if (segments.length === 1) {
    return SCALAR_FIELD_LABELS[head] ?? head;
  }
  const sectionLabel = SECTION_LABELS[head] ?? head;
  const index = typeof segments[1] === "number" ? segments[1] : -1;
  const identityField = ITEM_IDENTITY[head];
  const item =
    content && index >= 0 && identityField
      ? ((content as unknown as Record<string, { [key: string]: unknown }[]>)[head]?.[index] ??
        null)
      : null;
  const identity = item ? String(item[identityField] ?? "").trim() : "";
  const subject = identity ? `${sectionLabel}「${identity}」` : sectionLabel;
  if (segments.length === 2) return subject;
  const field = String(segments[2]);
  if (segments.length === 3) {
    return `${subject}的${ITEM_SCALAR_LABELS[field] ?? field}`;
  }
  const listIndex = typeof segments[3] === "number" ? segments[3] : -1;
  return `${subject}的第 ${listIndex + 1} 条${LIST_FIELD_LABELS[field] ?? field}`;
}
