import { describe, expect, it } from "vitest";
import type { Profile, ProfileTextParseResult } from "../types";
import { mergeParsedProfileValues } from "./profileText";

const current: Omit<Profile, "id" | "updated_at"> = {
  photo: "data:image/png;base64,photo",
  name: "原姓名",
  gender: "女",
  birth_year: "2000",
  phone: "13800000000",
  email: "old@example.com",
  city: "天津",
  target_city: "北京",
  job_intent: "后端工程师",
  personal_website: "https://example.com",
  github: "https://github.com/example",
  summary: "原总结",
  section_order: ["projects", "skills"],
  educations: [{ school: "原学校" } as never],
  experiences: [{ company: "原公司" } as never],
  campus_experiences: [],
  projects: [{ name: "原项目" } as never],
  skills: [{ name: "Python", level: "熟练" }],
  awards: [],
};

const parsed: ProfileTextParseResult = {
  ...current,
  name: "",
  phone: "",
  summary: "新总结",
  educations: [],
  experiences: [{ company: "新公司" } as never],
  projects: [],
  skills: [],
  warnings: [],
  recognition_source: "local",
};

describe("mergeParsedProfileValues", () => {
  it("updates recognized fields while retaining omitted profile data", () => {
    const merged = mergeParsedProfileValues(current, parsed);

    expect(merged.name).toBe("原姓名");
    expect(merged.phone).toBe("13800000000");
    expect(merged.summary).toBe("新总结");
    expect(merged.experiences).toEqual([{ company: "新公司" }]);
    expect(merged.educations).toEqual(current.educations);
    expect(merged.projects).toEqual(current.projects);
    expect(merged.skills).toEqual(current.skills);
  });

  it("never changes the locally managed photo or section order", () => {
    const merged = mergeParsedProfileValues(current, {
      ...parsed,
      photo: "",
      section_order: ["skills"],
    });

    expect(merged.photo).toBe(current.photo);
    expect(merged.section_order).toEqual(current.section_order);
  });
});
