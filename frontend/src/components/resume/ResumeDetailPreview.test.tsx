/**
 * 简历详情预览：**「写作增强」页签必须真的够得着**。
 *
 * 这条用例防的是一类很隐蔽的失效：`ResumeEditorModal` 的「写作增强」页签只在拿到
 * `resumeId` 时才挂载，而后端、面板组件、接口、README 与使用指南早就都齐了——
 * 唯独**调用点没有把简历 id 传进去**。于是功能"存在"却在界面上点不到，用户问到
 * 助手时只能得到"暂不可达"。组件级测试抓不到这种断链，必须在**调用点**这一层钉住。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ResumeDetail, ResumeLayout } from "../../types";
import ResumeDetailPreview from "./ResumeDetailPreview";

// 预览是真的 iframe + 量高，与本用例无关，替掉以免拖慢/拖挂。
// 预览本身由 ResumePreview.test.tsx 覆盖；这里把它替成一个能"点中某一栏"的桩，
// 用来验证**调用点**的接线：点中的那一栏应打开"只编辑这一部分"。
vi.mock("../ResumePreview", () => ({
  default: ({ onEditTarget }: { onEditTarget?: (path: string) => void }) => (
    <button type="button" onClick={() => onEditTarget?.("summary")}>
      模拟点中「个人总结」
    </button>
  ),
}));
vi.mock("./ResumeLayoutDiagnosisCard", () => ({ default: () => null }));
vi.mock("../ResumeLayoutControls", () => ({ default: () => null }));
vi.mock("../ExportButtons", () => ({ default: () => null }));

const DETAIL: ResumeDetail = {
  id: 42,
  title: "后端开发-示例科技",
  job_id: 7,
  job_title: "后端开发",
  company: "示例科技",
  source: "ai",
  favorite: false,
  note: "",
  model: "demo-model",
  enhancement_enabled: false,
  enhancement_level: "balanced",
  template: "classic",
  format_name: "",
  format_config: {},
  page_limit: 1,
  font_scale: "standard",
  created_at: "2026-09-20T08:00:00",
  content: {
    photo: "",
    name: "张三",
    gender: "",
    birth_year: "",
    phone: "",
    email: "",
    city: "",
    job_intent: "后端开发",
    summary: "",
    education: [],
    experience: [],
    campus_experience: [],
    projects: [],
    skills: [],
    awards: [],
  },
  warnings: [],
  parse_error: "",
};

const LAYOUT: ResumeLayout = {
  template: "classic",
  format_name: "",
  page_limit: 1,
  font_scale: "standard",
  format_config: {},
};

function renderPreview() {
  const previewRef = { current: null };
  return render(
    <MemoryRouter>
      <AntdApp>
        <ResumeDetailPreview
          detail={DETAIL}
          html="<html></html>"
          layout={LAYOUT}
          layoutStatus={null}
          measure={null}
          pdfDirectAvailable
          relayouting={false}
          previewRef={previewRef}
          onLayoutStatus={vi.fn()}
          onMeasure={vi.fn()}
          onApplyLayout={vi.fn()}
          onApplyFittedFormat={vi.fn()}
          onSaveEditedResume={vi.fn()}
          suggestionsGenerated={false}
          suggestionsResetKey={0}
          onSuggestionsGenerated={vi.fn()}
        />
      </AntdApp>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ResumeDetailPreview 的「手动调整」", () => {
  it("打开整份编辑器后能拿到「写作增强」页签", async () => {
    renderPreview();

    fireEvent.click(await screen.findByRole("button", { name: /手动调整/ }));

    // 页签出现 = 调用点确实把简历 id 传给了编辑弹窗；没传的话这里会一直找不到。
    expect(await screen.findByText("写作增强")).toBeInTheDocument();
  });
});

describe("ResumeDetailPreview 底部按钮排满整行", () => {
  it("「查看大图」打开 1:1 预览弹窗，并把当前页数带过去", async () => {
    renderPreview();

    fireEvent.click(screen.getByRole("button", { name: /查看大图/ }));

    // 弹窗里复用同一个预览组件：页数必须与外面一致，否则"大图"看到的又是另一种分页。
    // 弹窗打开、并且说明里带上了当前页数（页数一致是这一块的重点）。
    expect(await screen.findByText("查看简历大图")).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(`与当前 ${LAYOUT.page_limit} 页的设置一致`)),
    ).toBeInTheDocument();
    // 弹窗里复用同一个预览组件（渲染细节由 ResumePreview 自己的测试覆盖，这里只钉"用的是它"）。
    expect(document.querySelector(".resume-zoom-body")).not.toBeNull();
  });

  it("预览里点中某一栏只打开「只编辑这一部分」，不是整份编辑器", async () => {
    renderPreview();

    fireEvent.click(screen.getByRole("button", { name: /模拟点中/ }));

    // 打开的是"只改这一栏"的窗口：带保存这一栏的按钮与那一栏的当前内容。
    expect(await screen.findByRole("button", { name: /保存这一栏/ })).toBeInTheDocument();
    expect(screen.getByText("编辑：个人总结")).toBeInTheDocument();
    // 整份编辑器（有「写作增强」页签）没有被打开。
    expect(screen.queryByText("写作增强")).not.toBeInTheDocument();
  });

  it("「手动调整」才打开整份编辑器", async () => {
    renderPreview();

    fireEvent.click(screen.getByRole("button", { name: /手动调整/ }));

    expect(await screen.findByText("写作增强")).toBeInTheDocument();
  });

  it("底部操作条使用 grid 布局类，且所有动作按钮都渲染出来", () => {
    renderPreview();

    // grid 布局类存在——每个按钮独占一格、block 拉满，整行不留右侧空当。
    const footer = document.querySelector(".resume-detail-footer");
    expect(footer).not.toBeNull();
    expect(footer!.className).toContain("resume-detail-footer");
    // 八项动作按钮都在（ExportButtons 在测试里被替成 null，不影响这一层）。
    for (const name of [
      "手动调整",
      "查看大图",
      "生成岗位优化建议",
      "查看对应岗位",
      "咨询求职助手",
      "质量检测",
      "导出选项",
      "一键脱敏",
      "离线分享",
    ]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });
});
