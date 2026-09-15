/** 个人资料大分区的稳定顺序、标签和归一化规则。 */

export type ProfileSectionKey =
  | "basic_info"
  | "educations"
  | "experiences"
  | "campus_experiences"
  | "projects"
  | "skills"
  | "awards"
  | "summary";

export const DEFAULT_SECTION_ORDER: ProfileSectionKey[] = [
  "basic_info",
  "educations",
  "experiences",
  "campus_experiences",
  "projects",
  "skills",
  "awards",
  "summary",
];

export const SECTION_DRAG_THRESHOLD_PX = 6;

export const SECTION_LABELS: Record<ProfileSectionKey, string> = {
  basic_info: "基本信息",
  educations: "教育经历",
  experiences: "实习/工作经历",
  campus_experiences: "校园经历",
  projects: "项目经历",
  skills: "专业技能",
  awards: "荣誉奖项",
  summary: "个人总结 / 自我评价",
};

export function normalizeSectionOrder(value: string[] | undefined): ProfileSectionKey[] {
  const supported = new Set<ProfileSectionKey>(DEFAULT_SECTION_ORDER);
  const normalized = (value ?? []).filter((key): key is ProfileSectionKey =>
    supported.has(key as ProfileSectionKey),
  );
  return [...normalized, ...DEFAULT_SECTION_ORDER.filter((key) => !normalized.includes(key))];
}
