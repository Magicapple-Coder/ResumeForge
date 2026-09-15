/** 将预览中的结构化字段路径映射到编辑器标签和表单字段。 */

const TAB_BY_SECTION: Record<string, string> = {
  education: "education",
  experience: "experience",
  campus_experience: "campus",
  projects: "projects",
  skills: "skills",
  awards: "awards",
};

const MULTILINE_FIELDS = new Set([
  "courses",
  "achievements",
  "description",
  "tech_stack",
  "highlights",
]);

export function resolveEditorTarget(path: string): { tab: string; name: (string | number)[] } {
  const parts = path
    .split(".")
    .filter(Boolean)
    .map((part) => (/^\d+$/.test(part) ? Number(part) : part));
  const section = typeof parts[0] === "string" ? parts[0] : "";
  const lastPart = parts[parts.length - 1];
  const lastField = parts[parts.length - 2];
  // 预览中的数组要点各有独立路径，但编辑器以一个多行文本框维护整个数组。
  if (
    typeof lastPart === "number" &&
    typeof lastField === "string" &&
    MULTILINE_FIELDS.has(lastField)
  ) {
    parts.pop();
  }
  return { tab: TAB_BY_SECTION[section] ?? "basic", name: parts };
}
