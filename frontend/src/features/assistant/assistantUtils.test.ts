import { describe, expect, it } from "vitest";
import { summarizeSkillNames } from "./assistantUtils";

function skill(name: string) {
  return { name };
}

describe("summarizeSkillNames", () => {
  it("lists every name while they still fit", () => {
    expect(summarizeSkillNames([skill("简历诊断")])).toBe("简历诊断");
    expect(summarizeSkillNames([skill("简历诊断"), skill("面试追问")])).toBe("简历诊断、面试追问");
  });

  it("collapses the list instead of letting the header grow", () => {
    expect(summarizeSkillNames([skill("A"), skill("B"), skill("C")])).toBe("A、B 等 3 个");
  });
});
