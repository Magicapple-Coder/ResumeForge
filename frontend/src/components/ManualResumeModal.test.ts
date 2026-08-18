import { describe, expect, it } from "vitest";
import type { Job, Profile } from "../types";
import { profileToResumeContent } from "../utils/profileToResume";

const PROFILE: Profile = {
  id: 1,
  photo: "",
  name: "张三",
  gender: "",
  birth_year: "",
  phone: "13800000000",
  email: "test@example.com",
  city: "广州",
  target_city: "深圳",
  job_intent: "旧求职意向",
  personal_website: "",
  github: "",
  summary: "个人总结",
  section_order: [],
  educations: [
    {
      school: "示例大学",
      major: "软件工程",
      degree: "本科",
      start_date: "2023.09",
      end_date: "2027.06",
      gpa: "",
      courses: "数据结构\n操作系统",
      achievements: "一等奖学金",
      reference_file_name: "",
      reference_content: "",
    },
  ],
  experiences: [],
  campus_experiences: [],
  projects: [
    {
      name: "ResumeForge",
      role: "开发者",
      start_date: "2026.01",
      end_date: "至今",
      tech_stack: "React、FastAPI",
      description: "实现简历编辑",
      highlights: "支持岗位适配",
      reference_file_name: "",
      reference_content: "",
    },
  ],
  skills: [{ name: "TypeScript", level: "熟练" }],
  awards: [],
};

const JOB = {
  id: 8,
  title: "AI 应用客户端开发工程师",
} as Job;

describe("profileToResumeContent", () => {
  it("uses the current job before the stale profile intent and converts list fields", () => {
    const result = profileToResumeContent(PROFILE, JOB);

    expect(result.job_intent).toBe(JOB.title);
    expect(result.education[0].courses).toEqual(["数据结构", "操作系统"]);
    expect(result.projects[0].tech_stack).toEqual(["React", "FastAPI"]);
    expect(result.skills).toEqual([{ name: "TypeScript", level: "熟练" }]);
  });
});
