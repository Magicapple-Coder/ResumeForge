/** 简历正文分区顺序的前端归一化与调序工具。
 *
 * 与后端 `services/resume/resume_sections.py` 是同一套规则的两份实现——**刻意不共享**：
 * 这份清单要同时被浏览器里的预览控件和服务端的四个渲染器使用，跨端共享意味着要么
 * 前端多拉一个接口、要么后端渲染前发一次请求，两条路都比"复制七行常量"贵。
 * 两侧各有测试钉住「默认顺序一致」「归一化结果完整」，这是防止漂移的方式。
 */

/** 分区键 → 界面文案。与后端 SECTION_LABELS 保持逐字一致。 */
export const RESUME_SECTION_LABELS: Record<string, string> = {
  summary: "个人总结",
  education: "教育经历",
  experience: "实习/工作经历",
  campus_experience: "校园经历",
  projects: "项目经历",
  skills: "专业技能",
  awards: "荣誉奖项",
};

export const DEFAULT_RESUME_SECTION_ORDER: string[] = [
  "summary",
  "education",
  "experience",
  "campus_experience",
  "projects",
  "skills",
  "awards",
];

/**
 * 把任意存储值归一化成"七个键齐全、无重复、只含已知键"的顺序。
 *
 * 未出现在输入里的键按默认顺序补在后面：用户只调了前两项，不应该让其余五项消失。
 * 未知键丢弃而不是报错——它来自版式配置里的一个 JSON 字段，抛异常会让整份版式失效。
 */
export function normalizeSectionOrder(
  stored: unknown,
  defaultOrder: string[] = DEFAULT_RESUME_SECTION_ORDER,
): string[] {
  const known = new Set(defaultOrder);
  const ordered: string[] = [];
  if (Array.isArray(stored)) {
    for (const item of stored) {
      if (typeof item === "string" && known.has(item) && !ordered.includes(item)) {
        ordered.push(item);
      }
    }
  }
  for (const key of defaultOrder) {
    if (!ordered.includes(key)) {
      ordered.push(key);
    }
  }
  return ordered;
}

/** 把 `index` 上的分区上移 / 下移一格；越界时原样返回（调用方不必自己判边界）。 */
export function moveSection(order: string[], index: number, direction: -1 | 1): string[] {
  const target = index + direction;
  if (index < 0 || index >= order.length || target < 0 || target >= order.length) {
    return order;
  }
  const next = [...order];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
