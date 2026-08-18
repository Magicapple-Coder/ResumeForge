import type {
  Job,
  Profile,
  ResumeContent,
  ResumeEducation,
  ResumeExperience,
  ResumeProject,
} from "../types";

const splitLines = (value: string | undefined): string[] =>
  (value ?? "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);

const splitTechStack = (value: string | undefined): string[] =>
  (value ?? "")
    .split(/[\r\n,，、;；|]+/)
    .map((item) => item.trim())
    .filter(Boolean);

function hasText(value: Record<string, unknown>): boolean {
  return Object.values(value).some((item) => {
    if (Array.isArray(item)) return item.length > 0;
    return typeof item === "string" && item.trim().length > 0;
  });
}

/** 将资料页的多行字符串转换为简历编辑器使用的数组字段。 */
export function profileToResumeContent(profile: Profile, job?: Job | null): ResumeContent {
  const education: ResumeEducation[] = profile.educations
    .map((item) => ({
      school: item.school,
      major: item.major,
      degree: item.degree,
      start_date: item.start_date,
      end_date: item.end_date,
      gpa: item.gpa,
      courses: splitLines(item.courses),
      achievements: splitLines(item.achievements),
    }))
    .filter((item) => hasText(item as unknown as Record<string, unknown>));
  const experience: ResumeExperience[] = profile.experiences
    .map((item) => ({
      company: item.company,
      role: item.role,
      start_date: item.start_date,
      end_date: item.end_date,
      description: splitLines(item.description),
    }))
    .filter((item) => hasText(item as unknown as Record<string, unknown>));
  const campus_experience = profile.campus_experiences
    .map((item) => ({
      organization: item.organization,
      role: item.role,
      start_date: item.start_date,
      end_date: item.end_date,
      description: splitLines(item.description),
    }))
    .filter((item) => hasText(item as unknown as Record<string, unknown>));
  const projects: ResumeProject[] = profile.projects
    .map((item) => ({
      name: item.name,
      role: item.role,
      start_date: item.start_date,
      end_date: item.end_date,
      tech_stack: splitTechStack(item.tech_stack),
      description: splitLines(item.description),
      highlights: splitLines(item.highlights),
    }))
    .filter((item) => hasText(item as unknown as Record<string, unknown>));

  return {
    photo: profile.photo,
    name: profile.name,
    gender: profile.gender,
    birth_year: profile.birth_year,
    phone: profile.phone,
    email: profile.email,
    city: profile.city,
    job_intent: job?.title || profile.job_intent || "",
    summary: profile.summary,
    education,
    experience,
    campus_experience,
    projects,
    skills: profile.skills
      .map((item) => ({ name: item.name, level: item.level }))
      .filter((item) => hasText(item)),
    awards: profile.awards
      .map((item) => ({ name: item.name, date: item.date, description: item.description }))
      .filter((item) => hasText(item)),
  };
}
