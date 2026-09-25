/**
 * 「让 AI 按我的要求改这一栏」：当前内容区的**折叠**行为。
 *
 * 这一块以前是 `max-height: 72px; overflow-y: auto`，内容一长右边就竖一根滚动条
 * （用户反馈"不太好看"）。现在改成默认折到 4 行 + 「展开全文」。这里钉住三件事：
 * 长内容默认折叠、点了能看到全部、短内容不出现多余的展开按钮。
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { App as AntdApp } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ResumeContent } from "../../types";
import FieldRewritePanel from "./FieldRewritePanel";

vi.mock("../../api/resumeWriting", () => ({ rewriteResumeField: vi.fn() }));

// 长度贴近真实数据（演示库里的个人总结就是这个量级：超过三行）。
const LONG_SUMMARY =
  "3 年市场与运营经验，主导过从 0 到 1 的会员增长项目，擅长把一次性的活动经验沉淀成可复用的流程。" +
  "面向高级研发工程师画像，具备完整的数据驱动决策习惯，能把模糊的业务目标拆成可验证的实验；" +
  "熟悉私域运营与内容增长的全链路，能独立完成从选题、投放、复盘到沉淀方法论的过程；" +
  "在跨部门协作中负责需求收敛与排期，推动设计与研发按周交付，并把复盘结论写回流程文档。";

function content(overrides: Partial<ResumeContent> = {}): ResumeContent {
  return {
    name: "张三",
    summary: LONG_SUMMARY,
    projects: [
      {
        name: "会员增长系统",
        role: "后端",
        period: "2024",
        description: ["要点一", "要点二", "要点三", "要点四", "要点五"],
        highlights: [],
        tech_stack: [],
      },
    ],
    ...overrides,
  } as unknown as ResumeContent;
}

function renderPanel(path: string) {
  render(
    <AntdApp>
      <FieldRewritePanel resumeId={7} content={content()} path={path} onChange={vi.fn()} />
    </AntdApp>,
  );
}

afterEach(cleanup);

describe("当前内容的折叠显示", () => {
  it("长文本（个人总结）默认折叠，并给出展开入口", () => {
    renderPanel("summary");

    expect(screen.getByText(/展开全文/)).toBeInTheDocument();
    // 折叠时那一段仍然渲染（靠 CSS 截断行数），只是多了展开按钮——内容不会丢。
    expect(screen.getByText(/3 年市场与运营经验/)).toBeInTheDocument();
  });

  it("点「展开全文」看得到全部，再点「收起」回到折叠", () => {
    renderPanel("summary");

    fireEvent.click(screen.getByText(/展开全文/));
    expect(screen.getByText("收起")).toBeInTheDocument();

    fireEvent.click(screen.getByText("收起"));
    expect(screen.getByText(/展开全文/)).toBeInTheDocument();
  });

  it("要点很多时也折叠，展开文案带上条数", () => {
    renderPanel("projects.0.description");

    expect(screen.getByText("展开全文（共 5 条）")).toBeInTheDocument();
  });

  it("内容很短时不出现展开按钮", () => {
    render(
      <AntdApp>
        <FieldRewritePanel
          resumeId={7}
          content={content({ summary: "两年前端开发经验。" })}
          path="summary"
          onChange={vi.fn()}
        />
      </AntdApp>,
    );

    expect(screen.queryByText(/展开全文/)).not.toBeInTheDocument();
  });
});
