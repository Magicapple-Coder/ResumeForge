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

/**
 * 资料大分区的默认顺序。
 *
 * 这是**有意的产品决策**，不是随手排列：简历阅读者（HR、面试官）最关心的是
 * 「最近在做什么、做过什么项目」，所以把实习/工作经历与项目经历提到教育经历之前；
 * 教育经历只保留一段可查证的信息，放在技能之后。后端 `PROFILE_SECTION_KEYS`
 * 必须与本数组逐项一致（`PROFILE_SECTION_KEYS` 决定旧数据缺失分区时的补位顺序）。
 */
export const DEFAULT_SECTION_ORDER: ProfileSectionKey[] = [
  "basic_info",
  "experiences",
  "projects",
  "skills",
  "educations",
  "awards",
  "campus_experiences",
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
  const normalized = (value ?? []).filter(
    (key): key is ProfileSectionKey =>
      key !== "basic_info" && supported.has(key as ProfileSectionKey),
  );
  return [
    "basic_info",
    ...normalized,
    ...DEFAULT_SECTION_ORDER.filter((key) => key !== "basic_info" && !normalized.includes(key)),
  ];
}
