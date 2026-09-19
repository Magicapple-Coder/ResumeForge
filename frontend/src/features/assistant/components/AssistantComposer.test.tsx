/** 求职助手输入区：引用追问的「×」清除引用（只清上下文、不发送）。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AssistantComposer from "./AssistantComposer";
import type { AssistantQuotedMessage } from "../../../types";

function renderComposer(overrides: Partial<Parameters<typeof AssistantComposer>[0]> = {}) {
  const props = {
    content: "",
    attachments: [],
    sending: false,
    attachmentReads: 0,
    jobId: undefined,
    resumeId: undefined,
    includeProfile: false,
    webSearch: false,
    reasoningEffort: "" as const,
    skills: [],
    skillsLoaded: true,
    togglingSkillId: null,
    jobOptions: [],
    resumeOptions: [],
    onContentChange: vi.fn(),
    onJobChange: vi.fn(),
    onResumeChange: vi.fn(),
    onIncludeProfileChange: vi.fn(),
    onWebSearchChange: vi.fn(),
    onReasoningEffortChange: vi.fn(),
    onToggleSkill: vi.fn(),
    onManageSkills: vi.fn(),
    onAddAttachment: vi.fn(),
    onRemoveAttachment: vi.fn(),
    quoted: null,
    onClearQuote: vi.fn(),
    onSend: vi.fn(),
    onStop: vi.fn(),
    ...overrides,
  };
  return {
    props,
    ...render(
      <AntdApp>
        <AssistantComposer {...props} />
      </AntdApp>,
    ),
  };
}

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("AssistantComposer 引用追问", () => {
  it("显示引用标签与内容，点「×」清除引用且不发送", () => {
    const quoted: AssistantQuotedMessage = {
      id: 5,
      role: "assistant",
      excerpt: "这是被引用的回复内容",
    };
    const { props } = renderComposer({ quoted });

    expect(screen.getByText("引用助手的回复")).toBeInTheDocument();
    expect(screen.getByText("这是被引用的回复内容")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "取消引用" }));

    expect(props.onClearQuote).toHaveBeenCalledTimes(1);
    // 清除引用只是清空 quoted 上下文，绝不能顺带把消息发出去。
    expect(props.onSend).not.toHaveBeenCalled();
  });

  it("没有引用时不渲染引用标签", () => {
    renderComposer();
    expect(screen.queryByText(/引用/)).toBeNull();
  });
});
