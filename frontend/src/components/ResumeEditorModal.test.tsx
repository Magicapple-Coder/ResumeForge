import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ResumeContent } from "../types";
import ResumeEditorModal from "./ResumeEditorModal";

const CONTENT: ResumeContent = {
  photo: "",
  name: "张三",
  gender: "",
  birth_year: "",
  phone: "",
  email: "",
  city: "",
  job_intent: "产品运营专员",
  summary: "",
  education: [],
  experience: [],
  campus_experience: [],
  projects: [],
  skills: [],
  awards: [],
};

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ResumeEditorModal reference panel", () => {
  it("places the reference before the form in a collapsible narrow-screen section", () => {
    render(
      <AntdApp>
        <ResumeEditorModal
          open
          content={CONTENT}
          referencePanel={<div>岗位参考内容</div>}
          onClose={vi.fn()}
          onSave={vi.fn()}
        />
      </AntdApp>,
    );

    const referenceToggle = screen.getByRole("button", { name: /查看岗位要求/ });
    const referenceContainer = referenceToggle.closest(".resume-editor-reference");
    const editorContainer = screen.getByLabelText("姓名").closest(".resume-editor-main");

    expect(referenceToggle).toHaveAttribute("aria-expanded", "false");
    expect(referenceContainer?.parentElement?.firstElementChild).toBe(referenceContainer);
    expect(editorContainer).toBeInTheDocument();

    fireEvent.click(referenceToggle);
    expect(referenceToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("岗位参考内容")).toBeInTheDocument();
  });

  it("keeps the existing editor unchanged when no reference is supplied", () => {
    render(
      <AntdApp>
        <ResumeEditorModal open content={CONTENT} onClose={vi.fn()} onSave={vi.fn()} />
      </AntdApp>,
    );

    expect(screen.queryByText("查看岗位要求")).not.toBeInTheDocument();
    expect(screen.getByLabelText("姓名")).toHaveValue("张三");
  });

  it("opens the matching tab and focuses a multiline field selected from the preview", async () => {
    const content: ResumeContent = {
      ...CONTENT,
      projects: [
        {
          name: "预测性维护平台",
          role: "负责人",
          start_date: "2026.01",
          end_date: "2026.06",
          tech_stack: ["Python"],
          description: ["采集设备数据", "构建故障预警模型"],
          highlights: ["降低停机时间"],
        },
      ],
    };

    render(
      <AntdApp>
        <ResumeEditorModal
          open
          content={content}
          initialTarget="projects.0.description.1"
          onClose={vi.fn()}
          onSave={vi.fn()}
        />
      </AntdApp>,
    );

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "项目" })).toHaveAttribute("aria-selected", "true"),
    );
    const description = screen.getByLabelText("项目描述");
    expect(description).toHaveValue("采集设备数据\n构建故障预警模型");
    await waitFor(() => expect(description).toHaveFocus());
  });
});
