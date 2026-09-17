/**
 * 版面诊断面板：结论展示、自动一页的逐档搜索、以及"收到底也放不下"时的如实回报。
 *
 * 自动一页有两处最容易做错，两条都测：
 * 1. **够放下就停**——一步把字号缩到最小是最省事的写法，但那不是用户要的；
 * 2. **保存时原样回传版式参数**——`PATCH /layout` 是整体替换，传空模板名会把用户
 *    选好的样式模板和字号悄悄改掉。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ResumeFitCandidate, ResumeLayoutAnalysis } from "../../types";
import type { ResumePreviewHandle } from "../ResumePreview";
import ResumeLayoutDiagnosisCard from "./ResumeLayoutDiagnosisCard";

const apiMocks = vi.hoisted(() => ({
  analyzeResumeLayout: vi.fn(),
  updateResumeLayout: vi.fn(),
}));

vi.mock("../../api/resumes", () => apiMocks);

const LAYOUT = {
  template: "elegant",
  format_name: "compact",
  page_limit: 1,
  font_scale: "large" as const,
};

const MEASURE = { usedHeight: 2800, pageContentHeight: 2600, pageLimit: 1 };

function candidate(key: string, label: string, config: Record<string, number>): ResumeFitCandidate {
  return { key, label, config, css: `${key}:${JSON.stringify(config)}` };
}

function analysis(overrides: Partial<ResumeLayoutAnalysis> = {}): ResumeLayoutAnalysis {
  return {
    diagnosis: {
      status: "overflow",
      status_label: "超出所选页数",
      summary: "内容按当前版式需要 2 页，超过所选的 1 页。",
      fill: 1.08,
      pages_needed: 2,
      page_limit: 1,
      pages: [],
      suggestions: [
        { kind: "restructure", title: "先看能不能靠重排放下", detail: "把最相关的经历提到前面。" },
      ],
    },
    fit_ladder: [],
    fit_room: {
      has_room: true,
      steps: 3,
      font_floor_px: 12,
      font_adjust_floor: 0.88,
      font_floor_note: "正文字号最多缩到 12px（≈9pt）。",
    },
    ...overrides,
  };
}

/** 造一个逐档测量的假预览：按 css 决定这一档放不放得下。 */
function fakePreview(
  fitsAt: string | null,
  measurements: Record<string, number> = {},
): React.RefObject<ResumePreviewHandle | null> {
  const ref = createRef<ResumePreviewHandle>();
  (ref as { current: ResumePreviewHandle | null }).current = {
    measureWithProbe(css: string) {
      if (!css) return null;
      if (fitsAt !== null && css.includes(fitsAt)) {
        return { usedHeight: 2500, pageContentHeight: 2600, pageLimit: 1 };
      }
      return { usedHeight: measurements[css] ?? 2800, pageContentHeight: 2600, pageLimit: 1 };
    },
  };
  return ref;
}

function renderCard(props: Partial<React.ComponentProps<typeof ResumeLayoutDiagnosisCard>> = {}) {
  return render(
    <AntdApp>
      <ResumeLayoutDiagnosisCard
        resumeId={7}
        measure={MEASURE}
        overflow
        previewRef={fakePreview(null)}
        layout={LAYOUT}
        onApplied={vi.fn()}
        onAddPage={vi.fn()}
        {...props}
      />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.analyzeResumeLayout.mockReset();
  apiMocks.updateResumeLayout.mockReset();
});

afterEach(cleanup);

describe("ResumeLayoutDiagnosisCard", () => {
  it("shows the diagnosis and the ordered suggestions", async () => {
    apiMocks.analyzeResumeLayout.mockResolvedValue(analysis());
    renderCard();

    expect(await screen.findByText("超出所选页数")).toBeInTheDocument();
    expect(screen.getByText("内容按当前版式需要 2 页，超过所选的 1 页。")).toBeInTheDocument();
    expect(screen.getByText("先看能不能靠重排放下")).toBeInTheDocument();
    expect(screen.getByText(/把最相关的经历提到前面/)).toBeInTheDocument();
  });

  it("hides the whole card when the diagnosis is unavailable and nothing looks wrong", async () => {
    // 诊断接口打不通、预览也没判定溢出时，整块消失——留一个只有标题的空面板
    // 只会让用户以为功能坏了。
    apiMocks.analyzeResumeLayout.mockRejectedValue(new Error("接口不可用"));
    renderCard({ overflow: false });

    await waitFor(() => expect(apiMocks.analyzeResumeLayout).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("版面诊断")).not.toBeInTheDocument(), {
      timeout: 3000,
    });
  });

  it("keeps showing when the layout is healthy, because that answers 'is this OK'", async () => {
    apiMocks.analyzeResumeLayout.mockResolvedValue(
      analysis({
        diagnosis: {
          status: "healthy",
          status_label: "合适",
          summary: "正文占了 90%，版面合适。",
          fill: 0.9,
          pages_needed: 1,
          page_limit: 1,
          pages: [],
          suggestions: [
            { kind: "restructure", title: "占用 90%，保持即可", detail: "直接导出就好。" },
          ],
        },
      }),
    );
    renderCard({ overflow: false });

    expect(await screen.findByText("合适")).toBeInTheDocument();
    expect(screen.getByText("占用 90%，保持即可")).toBeInTheDocument();
    // 放得下就不该出现「自动一页」。
    expect(screen.queryByRole("button", { name: /自动一页/ })).not.toBeInTheDocument();
  });

  it("does not offer auto-fit when it already fits", async () => {
    apiMocks.analyzeResumeLayout.mockResolvedValue(
      analysis({
        diagnosis: {
          status: "healthy",
          status_label: "合适",
          summary: "版面合适。",
          fill: 0.9,
          pages_needed: 1,
          page_limit: 1,
          pages: [],
          suggestions: [{ kind: "restructure", title: "保持即可", detail: "直接导出就好。" }],
        },
      }),
    );
    renderCard({ overflow: false });

    await screen.findByText("合适");
    expect(screen.queryByRole("button", { name: /自动一页/ })).not.toBeInTheDocument();
  });

  it("stops at the first rung that fits instead of shrinking to the smallest", async () => {
    const ladder = [
      candidate("padding", "页边距收到 12mm", { page_padding: 12 }),
      candidate("line_height", "行高收到 1.55", { line_height: 1.55 }),
      candidate("font_scale_adjust", "字号收到 0.88 倍", { font_scale_adjust: 0.88 }),
    ];
    apiMocks.analyzeResumeLayout.mockResolvedValue(analysis({ fit_ladder: ladder }));
    // 只有第二档放得下。
    apiMocks.updateResumeLayout.mockResolvedValue({ format_config: ladder[1].config });
    const onApplied = vi.fn();

    renderCard({ previewRef: fakePreview("1.55"), onApplied });
    // 等按钮出现再点：「超出所选页数」这句在 ladder 到位前后都在，
    // 拿它当同步点会在 fit_ladder 还是空的时候就去点，于是什么也不会发生。
    fireEvent.click(await screen.findByRole("button", { name: /自动一页/ }));

    await waitFor(() => expect(apiMocks.updateResumeLayout).toHaveBeenCalledTimes(1));
    // 停在第二档，而不是一路缩到 0.88。
    expect(apiMocks.updateResumeLayout.mock.calls[0][1].format_config).toEqual(ladder[1].config);
    expect(onApplied).toHaveBeenCalledWith(ladder[1].config);
  });

  it("passes the current layout through so the template is not reset", async () => {
    const ladder = [candidate("padding", "页边距收到 12mm", { page_padding: 12 })];
    apiMocks.analyzeResumeLayout.mockResolvedValue(analysis({ fit_ladder: ladder }));
    apiMocks.updateResumeLayout.mockResolvedValue({ format_config: ladder[0].config });

    renderCard({ previewRef: fakePreview("12") });
    fireEvent.click(await screen.findByRole("button", { name: /自动一页/ }));

    await waitFor(() => expect(apiMocks.updateResumeLayout).toHaveBeenCalled());
    const [, payload] = apiMocks.updateResumeLayout.mock.calls[0];
    // PATCH 是整体替换：漏一个字段就等于把它重置成默认值。
    expect(payload.template).toBe("elegant");
    expect(payload.format_name).toBe("compact");
    expect(payload.font_scale).toBe("large");
    expect(payload.page_limit).toBe(1);
  });

  it("says it plainly when nothing fits, instead of pretending it worked", async () => {
    const ladder = [
      candidate("font_scale_adjust", "字号收到 0.88 倍", { font_scale_adjust: 0.88 }),
    ];
    apiMocks.analyzeResumeLayout.mockResolvedValue(analysis({ fit_ladder: ladder }));

    // 每一档都放不下。
    renderCard({ previewRef: fakePreview(null) });
    fireEvent.click(await screen.findByRole("button", { name: /自动一页/ }));

    expect(await screen.findByText(/版式已经收到最紧了/)).toBeInTheDocument();
    // 没成功就不能写库，也不能告诉父组件"已应用"。
    expect(apiMocks.updateResumeLayout).not.toHaveBeenCalled();
  });

  it("keeps telling the user about overflow when the diagnosis request fails", async () => {
    apiMocks.analyzeResumeLayout.mockRejectedValue(new Error("接口不可用"));
    renderCard({ overflow: true });

    // 只是静默地不显示面板，用户会以为版面没问题。
    expect(await screen.findByText(/内容超出了 1 页/)).toBeInTheDocument();
  });

  it("disables auto-fit while another render is in flight", async () => {
    const ladder = [candidate("padding", "页边距收到 12mm", { page_padding: 12 })];
    apiMocks.analyzeResumeLayout.mockResolvedValue(analysis({ fit_ladder: ladder }));
    renderCard({ previewRef: fakePreview("12"), disabled: true });

    await screen.findByRole("button", { name: /自动一页/ });
    expect(screen.getByRole("button", { name: /自动一页/ })).toBeDisabled();
  });

  it("offers adding a page with the floor note", async () => {
    const ladder = [candidate("padding", "页边距收到 12mm", { page_padding: 12 })];
    apiMocks.analyzeResumeLayout.mockResolvedValue(analysis({ fit_ladder: ladder }));
    const onAddPage = vi.fn();
    renderCard({ previewRef: fakePreview("12"), onAddPage });

    await screen.findByRole("button", { name: /自动一页/ });
    expect(screen.getByText(/最多缩到 12px/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /增加到 2 页/ }));
    expect(onAddPage).toHaveBeenCalled();
  });
});
