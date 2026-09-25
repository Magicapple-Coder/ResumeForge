/** 简历字段路径的读写：预览点中的那一栏要能精确定位，写回时不能动到别处。 */

import { describe, expect, it } from "vitest";
import type { ResumeContent } from "../types";
import {
  describeResumeFieldPath,
  isLineListPath,
  parseResumeFieldPath,
  readResumeFieldByPath,
  readResumeLinesByPath,
  readResumeValueByPath,
  toWholeSegmentPath,
  writeResumeFieldByPath,
  writeResumeValueByPath,
} from "./resumeFieldPath";

function content(): ResumeContent {
  return {
    name: "张示例",
    summary: "一段总结",
    projects: [
      {
        name: "会员增长系统",
        role: "前端负责人",
        description: ["第一条要点", "第二条要点"],
      },
    ],
    experience: [{ company: "示例科技有限公司", role: "示例岗位" }],
  } as ResumeContent;
}

describe("parseResumeFieldPath", () => {
  it("数字段变成下标，其余保持字符串", () => {
    expect(parseResumeFieldPath("projects.0.description.1")).toEqual([
      "projects",
      0,
      "description",
      1,
    ]);
  });
});

describe("readResumeFieldByPath", () => {
  it("读到指定那一栏的文本", () => {
    expect(readResumeFieldByPath(content(), "projects.0.description.1")).toBe("第二条要点");
    expect(readResumeFieldByPath(content(), "summary")).toBe("一段总结");
  });

  it("指不到或是数组时返回空串（不抛异常）", () => {
    expect(readResumeFieldByPath(content(), "projects.9.name")).toBe("");
    expect(readResumeFieldByPath(content(), "projects.0.description")).toBe("");
    expect(readResumeFieldByPath(null, "summary")).toBe("");
  });

  it("按段读值可以拿到数组本身（编辑器里列表字段就是一个数组）", () => {
    expect(readResumeValueByPath(content(), ["projects", 0, "description"])).toEqual([
      "第一条要点",
      "第二条要点",
    ]);
  });
});

describe("writeResumeFieldByPath", () => {
  it("只改目标那一栏，其余内容与引用不变", () => {
    const before = content();
    const after = writeResumeFieldByPath(before, "projects.0.description.1", "改过的第二条");

    expect(after.projects[0].description).toEqual(["第一条要点", "改过的第二条"]);
    // 没被改到的分支保持原引用：只重渲染真正变了的部分。
    expect(after.experience).toBe(before.experience);
    expect(after.projects[0].role).toBe("前端负责人");
    // 原对象没被就地修改。
    expect(before.projects[0].description[1]).toBe("第二条要点");
  });

  it("顶层标量也能写", () => {
    const after = writeResumeFieldByPath(content(), "summary", "新的总结");
    expect(after.summary).toBe("新的总结");
    expect(after.name).toBe("张示例");
  });

  it("路径指不到时不改动内容（宁可不动，也不要造出奇怪的形状）", () => {
    const before = content();
    const after = writeResumeFieldByPath(before, "projects.9.name", "X");
    expect(after).toEqual(before);
  });
});

describe("describeResumeFieldPath", () => {
  it("带上条目名，用户才知道改的是哪一条", () => {
    const label = describeResumeFieldPath("projects.0.description.1", content());
    expect(label).toContain("项目经历");
    expect(label).toContain("会员增长系统");
    expect(label).toContain("第 2 条");
  });

  it("顶层字段与条目内字段各有说法", () => {
    expect(describeResumeFieldPath("summary", content())).toBe("个人总结");
    expect(describeResumeFieldPath("experience.0.company", content())).toContain("公司");
  });

  it("没有内容时也能给出可读的说明（不崩）", () => {
    expect(describeResumeFieldPath("projects.0.description.0")).toContain("项目经历");
  });
});

describe("整段（若干条要点）的路径", () => {
  it("认得出哪些字段是'分成若干条'的", () => {
    expect(isLineListPath("experience.0.description")).toBe(true);
    expect(isLineListPath("campus_experience.0.description")).toBe(true);
    expect(isLineListPath("projects.1.highlights")).toBe(true);
    // 单条要点（4 段）与普通标量都不是"整段"
    expect(isLineListPath("experience.0.description.1")).toBe(false);
    expect(isLineListPath("experience.0.company")).toBe(false);
    expect(isLineListPath("summary")).toBe(false);
  });

  it("把单条要点收敛成它所属的那一段", () => {
    expect(toWholeSegmentPath("projects.0.description.1")).toBe("projects.0.description");
    // 本来就是整段（或不是要点字段）就原样返回
    expect(toWholeSegmentPath("projects.0.description")).toBe("projects.0.description");
    expect(toWholeSegmentPath("experience.0.company")).toBe("experience.0.company");
  });

  it("读得出全部要点", () => {
    expect(readResumeLinesByPath(content(), "projects.0.description")).toEqual([
      "第一条要点",
      "第二条要点",
    ]);
    expect(readResumeLinesByPath(content(), "summary")).toEqual([]);
  });

  it("整段能按数组写回，且不动别的分支", () => {
    const before = content();
    const after = writeResumeValueByPath(before, "projects.0.description", ["A", "B", "C"]);
    expect(after.projects[0].description).toEqual(["A", "B", "C"]);
    expect(after.projects[0].name).toBe("会员增长系统");
    expect(before.projects[0].description).toEqual(["第一条要点", "第二条要点"]);
  });

  it("字符串写回是数组写回的薄壳（同一份实现）", () => {
    const content1 = content();
    expect(writeResumeFieldByPath(content1, "summary", "新总结").summary).toBe("新总结");
    expect(writeResumeValueByPath(content1, "summary", "新总结").summary).toBe("新总结");
  });
});
