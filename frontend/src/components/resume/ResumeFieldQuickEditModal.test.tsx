/** 「只编辑选中的这一部分」：只改那一栏、保存走同一个回调。 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntdApp } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ResumeContent } from "../../types";
import { readResumeFieldByPath } from "../../utils/resumeFieldPath";
import ResumeFieldQuickEditModal from "./ResumeFieldQuickEditModal";

const apiMocks = vi.hoisted(() => ({ rewriteResumeField: vi.fn() }));
vi.mock("../../api/resumeWriting", () => ({
  rewriteResumeField: apiMocks.rewriteResumeField,
}));

const CONTENT: ResumeContent = {
  name: "张三",
  job_intent: "后端开发",
  summary: "原来的总结",
  projects: [
    {
      name: "会员增长系统",
      role: "后端",
      period: "2024",
      description: ["第一条要点", "第二条要点"],
      highlights: [],
      tech_stack: [],
    },
  ],
} as unknown as ResumeContent;

function renderModal(path: string, onSaved = vi.fn().mockResolvedValue(undefined)) {
  const onClose = vi.fn();
  render(
    <AntdApp>
      <ResumeFieldQuickEditModal
        open
        resumeId={7}
        content={CONTENT}
        path={path}
        onClose={onClose}
        onSaved={onSaved}
      />
    </AntdApp>,
  );
  return { onSaved, onClose };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ResumeFieldQuickEditModal", () => {
  it("打开时带出这一栏的当前内容，并说明只改这一处", () => {
    renderModal("summary");

    expect(screen.getByText("编辑：个人总结")).toBeInTheDocument();
    expect(screen.getByLabelText("这一栏的内容")).toHaveValue("原来的总结");
    expect(screen.getByText(/只改你选中的这一处/)).toBeInTheDocument();
  });

  it("列表栏按「一行一条」编辑，保存时写回数组且不动其它栏", async () => {
    const { onSaved } = renderModal("projects.0.description");

    const textarea = screen.getByLabelText("这一栏的内容");
    expect(textarea).toHaveValue("第一条要点\n第二条要点");

    fireEvent.change(textarea, { target: { value: "第一条要点\n第二条要点改过了\n新增一条" } });
    fireEvent.click(screen.getByRole("button", { name: /保存这一栏/ }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    const saved = onSaved.mock.calls[0][0] as ResumeContent;
    // 这一栏按行写回数组
    expect(readResumeFieldByPath(saved, "projects.0.description.0")).toBe("第一条要点");
    expect(readResumeFieldByPath(saved, "projects.0.description.1")).toBe("第二条要点改过了");
    // 其它栏原封不动
    expect(saved.summary).toBe("原来的总结");
    expect(saved.name).toBe("张三");
  });

  it("单条要点也能只改这一条", async () => {
    const { onSaved } = renderModal("projects.0.description.1");

    fireEvent.change(screen.getByLabelText("这一栏的内容"), { target: { value: "只改第二条" } });
    fireEvent.click(screen.getByRole("button", { name: /保存这一栏/ }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const saved = onSaved.mock.calls[0][0] as ResumeContent;
    expect(readResumeFieldByPath(saved, "projects.0.description.1")).toBe("只改第二条");
    expect(readResumeFieldByPath(saved, "projects.0.description.0")).toBe("第一条要点");
  });

  it("取消不会触发保存", () => {
    const { onSaved, onClose } = renderModal("summary");

    fireEvent.click(screen.getByRole("button", { name: /取\s*消/ }));

    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
