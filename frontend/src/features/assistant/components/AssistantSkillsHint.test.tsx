import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AssistantSkill } from "../../../types";
import { summarizeSkillNames } from "../assistantUtils";
import AssistantSkillsHint from "./AssistantSkillsHint";

function skill(name: string): AssistantSkill {
  return {
    id: name.length,
    name,
    description: "",
    enabled: true,
    source_name: `${name}.md`,
    prompt_chars: 100,
    files: [],
    updated_at: "2026-08-20T10:00:00",
  };
}

afterEach(cleanup);

describe("summarizeSkillNames", () => {
  it("lists every name while they still fit", () => {
    expect(summarizeSkillNames([skill("简历诊断")])).toBe("简历诊断");
    expect(summarizeSkillNames([skill("简历诊断"), skill("面试追问")])).toBe("简历诊断、面试追问");
  });

  it("collapses the list instead of letting the header grow", () => {
    expect(summarizeSkillNames([skill("A"), skill("B"), skill("C")])).toBe("A、B 等 3 个");
  });
});

describe("AssistantSkillsHint", () => {
  it("renders nothing when no skill is enabled", () => {
    const { container } = render(<AssistantSkillsHint skills={[]} onManage={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("opens the settings page for the current skills", () => {
    const onManage = vi.fn();
    render(<AssistantSkillsHint skills={[skill("简历诊断")]} onManage={onManage} />);

    fireEvent.click(screen.getByRole("button", { name: "已启用 1 个助手技能，点击管理" }));

    expect(onManage).toHaveBeenCalledOnce();
  });
});
