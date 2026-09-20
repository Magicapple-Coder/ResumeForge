/** 版本对比：字段级人性化视图 + 计算函数。
 *
 * 覆盖：有变化的字段才出卡片、完全一致的字段进「未变化」折叠、列表条目 +/- 标记、
 * photo 显示为 [图片]（不暴露 base64）、底部「查看原始差异」可展开（兜底）。
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import ResumeFieldDiffView from "./ResumeFieldDiffView";
import { computeFieldDiff } from "../utils/resumeFieldDiff";
import type { DiffViewData, ListSectionDiff, StringSectionDiff } from "../types/resumeFieldDiff";
import type { ResumeContent } from "../types/resume";
import type { ResumeDiff } from "../types/resumeWriting";

function makeBase(): ResumeContent {
  return {
    photo: "data:image/png;base64,AAAAAAAAAA",
    name: "张三",
    gender: "男",
    birth_year: "1999",
    phone: "13800000000",
    email: "zhang@x.com",
    city: "北京",
    job_intent: "后端工程师",
    summary: "热爱编程",
    education: [
      {
        school: "北京大学",
        major: "计算机科学",
        degree: "本科",
        start_date: "2017",
        end_date: "2021",
        gpa: "",
        courses: [],
        achievements: [],
      },
    ],
    experience: [],
    campus_experience: [],
    projects: [],
    skills: [{ name: "Go", level: "熟练" }],
    awards: [],
  };
}

const RAW: ResumeDiff = {
  base_id: 1,
  against_id: 2,
  base_title: "版本 A",
  against_title: "版本 B",
  stats: { added: 1, removed: 1, unchanged: 1 },
  lines: [{ type: "unchanged", text: '"name": "张三"', tokens: [] }],
};

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("computeFieldDiff", () => {
  it("只把有变化的字段放进 changed，未变的进 unchangedLabels", () => {
    const base = makeBase();
    const against = { ...makeBase(), name: "李四" };
    const r = computeFieldDiff(base, against, "A", "B");
    const changedKeys = r.changed.map((s) => s.key);
    expect(changedKeys).toContain("name");
    expect(changedKeys).not.toContain("email");
    expect(r.unchangedLabels).toContain("邮箱");
  });

  it("photo 用 [图片] 占位，不暴露 base64", () => {
    const base = makeBase();
    const against = { ...makeBase(), photo: "" };
    const r = computeFieldDiff(base, against, "A", "B");
    const photo = r.changed.find((s) => s.key === "photo") as StringSectionDiff | undefined;
    expect(photo).toBeDefined();
    expect(photo!.oldText).toBe("[图片]");
    expect(photo!.oldText).not.toContain("base64");
    expect(photo!.newText).toBe("");
  });

  it("列表字段：新增条目标记 added、删除条目标记 removed、未变条目计数", () => {
    const base = makeBase();
    const against = {
      ...makeBase(),
      skills: [
        { name: "Go", level: "熟练" },
        { name: "Python", level: "了解" },
      ],
    };
    const r = computeFieldDiff(base, against, "A", "B");
    const skills = r.changed.find((s) => s.key === "skills") as ListSectionDiff;
    expect(skills.type).toBe("list");
    expect(skills.added.map((i) => i.title)).toContain("Python");
    expect(skills.removed.length).toBe(0);
    expect(skills.unchangedCount).toBe(1);
  });

  it("列表字段：修改条目拆出子字段差异（熟练度 熟练 → 精通）", () => {
    const base = makeBase();
    const against = { ...makeBase(), skills: [{ name: "Go", level: "精通" }] };
    const r = computeFieldDiff(base, against, "A", "B");
    const skills = r.changed.find((s) => s.key === "skills") as ListSectionDiff;
    expect(skills.modified.length).toBe(1);
    expect(skills.modified[0].key).toBe("Go");
    const sub = skills.modified[0].subfields.find(
      (s) => s.kind === "string" && s.label === "熟练度",
    );
    expect(sub).toBeDefined();
    if (sub && sub.kind === "string") {
      expect(sub.oldText).toBe("熟练");
      expect(sub.newText).toBe("精通");
    }
  });

  it("完全一致时 changed 为空", () => {
    const base = makeBase();
    const r = computeFieldDiff(base, makeBase(), "A", "B");
    expect(r.changed.length).toBe(0);
    expect(r.unchangedLabels.length).toBe(15);
  });
});

describe("ResumeFieldDiffView", () => {
  const base = makeBase();
  const against = { ...makeBase(), name: "李四", photo: "" };
  const field = computeFieldDiff(base, against, "A", "B");
  const data: DiffViewData = { raw: RAW, field };

  it("有变化的字段出卡片、未变化折叠、原始差异兜底可展开", () => {
    render(<ResumeFieldDiffView data={data} />);
    // 变化字段卡片标题
    expect(screen.getByText("姓名")).toBeInTheDocument();
    // 未变化字段折叠头
    expect(screen.getByText(/个字段未变化/)).toBeInTheDocument();
    // 原始差异兜底折叠头
    expect(screen.getByText("查看原始差异")).toBeInTheDocument();
    // 统计 chips 保留
    expect(screen.getByText("新增 1")).toBeInTheDocument();
  });

  it("photo 显示为 [图片]，不出现 base64", () => {
    render(<ResumeFieldDiffView data={data} />);
    expect(screen.getByText("[图片]")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("base64");
  });

  it("列表新增条目以 + 标记（data-sign=added）", () => {
    const base2 = makeBase();
    const against2 = {
      ...makeBase(),
      skills: [
        { name: "Go", level: "熟练" },
        { name: "Python", level: "了解" },
      ],
    };
    const f = computeFieldDiff(base2, against2, "A", "B");
    render(<ResumeFieldDiffView data={{ raw: RAW, field: f }} />);
    expect(document.querySelector('[data-sign="added"]')).not.toBeNull();
    expect(screen.getAllByText(/Python/).length).toBeGreaterThan(0);
  });
});
