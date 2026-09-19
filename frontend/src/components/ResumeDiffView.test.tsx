/** 版本对比视图：三态高亮与词级 token 渲染。 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ResumeDiff } from "../types/resumeWriting";
import ResumeDiffView from "./ResumeDiffView";

const DIFF: ResumeDiff = {
  base_id: 1,
  against_id: 2,
  base_title: "版本 A",
  against_title: "版本 B",
  stats: { added: 1, removed: 1, unchanged: 1 },
  lines: [
    { type: "unchanged", text: '"name": "张三"', tokens: [] },
    {
      type: "removed",
      text: "负责 后端 服务 开发",
      tokens: [
        { type: "unchanged", text: "负责" },
        { type: "removed", text: "后端" },
        { type: "unchanged", text: "服务" },
      ],
    },
    {
      type: "added",
      text: "负责 前端 服务 开发",
      tokens: [
        { type: "unchanged", text: "负责" },
        { type: "added", text: "前端" },
        { type: "unchanged", text: "服务" },
      ],
    },
  ],
};

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ResumeDiffView", () => {
  it("渲染标题与统计", () => {
    render(<ResumeDiffView diff={DIFF} />);
    expect(screen.getByText("版本 A")).toBeInTheDocument();
    expect(screen.getByText("版本 B")).toBeInTheDocument();
    expect(screen.getByText("新增 1")).toBeInTheDocument();
    expect(screen.getByText("删除 1")).toBeInTheDocument();
    expect(screen.getByText("未变 1")).toBeInTheDocument();
  });

  it("按三态渲染行，并渲染词级 token", () => {
    render(<ResumeDiffView diff={DIFF} />);
    const rows = document.querySelectorAll("[data-line-type]");
    expect(rows.length).toBe(3);
    expect(rows[0].getAttribute("data-line-type")).toBe("unchanged");
    expect(rows[1].getAttribute("data-line-type")).toBe("removed");
    expect(rows[2].getAttribute("data-line-type")).toBe("added");
    expect(screen.getByText(/后端/)).toBeInTheDocument();
    expect(screen.getByText(/前端/)).toBeInTheDocument();
  });
});
