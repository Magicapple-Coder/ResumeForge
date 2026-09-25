/**
 * 版式控件：模板"选中即见预览"与无级字号滑块。
 *
 * 两块都是**看不见的错最容易溜过去**的地方：模板入口合并后如果只是换了个名字、
 * 预览没真的渲染出来，用户还是盲选；滑块如果每拖一下都发请求，界面会卡、后端会被刷。
 * 所以这里把"能看到预览""拖动不发请求、防抖后只发一次""恢复默认"都钉住。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TEMPLATE_CATALOG } from "../test/resumeFixtures";
import type { ResumeLayout } from "../types";
import type { ResumePreviewHandle } from "./ResumePreview";
import ResumeLayoutControls from "./ResumeLayoutControls";

const apiMocks = vi.hoisted(() => ({
  fetchResumeTemplates: vi.fn(),
  previewResumeTemplate: vi.fn(),
}));

// 展开真实模块再覆盖：生产代码新增导出时不会因为这里只列了两个而直接抛错。
vi.mock("../api/resumes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/resumes")>()),
  fetchResumeTemplates: apiMocks.fetchResumeTemplates,
  previewResumeTemplate: apiMocks.previewResumeTemplate,
}));

const DEFAULT_LAYOUT: ResumeLayout = {
  template: "classic",
  format_name: "",
  page_limit: 1,
  font_scale: "standard",
};

/** 假的预览句柄：只记录 setLiveProbe 被调过什么，不涉及真实 iframe。 */
function makePreviewRef() {
  const setLiveProbe = vi.fn();
  const measureWithProbe = vi.fn(() => null);
  const ref = createRef<ResumePreviewHandle>();
  (ref as { current: ResumePreviewHandle | null }).current = { setLiveProbe, measureWithProbe };
  return { ref, setLiveProbe, measureWithProbe };
}

function renderControls(
  props: Partial<React.ComponentProps<typeof ResumeLayoutControls>> = {},
  onChange = vi.fn(),
) {
  render(
    <AntdApp>
      <ResumeLayoutControls layout={DEFAULT_LAYOUT} onChange={onChange} {...props} />
    </AntdApp>,
  );
  return onChange;
}

beforeEach(() => {
  apiMocks.fetchResumeTemplates.mockReset();
  apiMocks.previewResumeTemplate.mockReset();
  apiMocks.fetchResumeTemplates.mockResolvedValue(TEMPLATE_CATALOG);
  apiMocks.previewResumeTemplate.mockResolvedValue("<html><body>简历</body></html>");
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

/** 键盘可访问：方向键微调字号。rc-slider 读的是 `keyCode`/`which`，不是 `key`。 */
function pressArrow(target: Element, direction: "ArrowLeft" | "ArrowRight") {
  const keyCode = direction === "ArrowRight" ? 39 : 37;
  fireEvent.keyDown(target, { key: direction, keyCode, which: keyCode });
}

describe("ResumeLayoutControls · 选模板即见预览（C2）", () => {
  it("模板入口合并成一个按钮，不再有单独的「看效果」", async () => {
    renderControls();
    expect(
      await screen.findByRole("button", { name: "选择简历模板并预览效果" }),
    ).toBeInTheDocument();
    // 合并后不该再出现原来那对分开的按钮里的「看效果」。
    expect(screen.queryByRole("button", { name: /看效果/ })).not.toBeInTheDocument();
  });

  it("点开模板入口就能看到每种模板的真实渲染，选中即应用", async () => {
    const onChange = renderControls();

    fireEvent.click(await screen.findByRole("button", { name: "选择简历模板并预览效果" }));

    // 主路径：打开后每个模板都用真实渲染接口出一张预览，而不是名字清单。
    await waitFor(() =>
      expect(apiMocks.previewResumeTemplate).toHaveBeenCalledTimes(
        TEMPLATE_CATALOG.templates.length,
      ),
    );
    expect(apiMocks.previewResumeTemplate).toHaveBeenCalledWith(
      expect.objectContaining({ template_name: "modern" }),
    );
    expect(await screen.findByTitle("现代 预览")).toBeInTheDocument();

    // 选模板与看效果是同一步：点「用这个模板」直接写入并重渲染，没有额外确认。
    const useButtons = screen.getAllByRole("button", { name: "用这个模板" });
    fireEvent.click(useButtons[0]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toMatchObject({ template: "modern" });
  });
});

describe("ResumeLayoutControls · 无级字号滑块（C3）", () => {
  it("拖动时即时反馈、不发请求；静置后只提交一次", async () => {
    const { ref, setLiveProbe } = makePreviewRef();
    const onChange = renderControls({ previewRef: ref });

    const slider = await screen.findByRole("slider");
    // 键盘可访问：方向键微调字号（这也是唯一的"拖动"入口，测试直接用它）。
    pressArrow(slider, "ArrowRight");
    pressArrow(slider, "ArrowRight");
    pressArrow(slider, "ArrowRight");

    // 中间态：预览被本地探针缩放了，但没有外发任何版式请求。
    expect(setLiveProbe).toHaveBeenCalled();
    const probeCalls = setLiveProbe.mock.calls;
    expect(probeCalls[probeCalls.length - 1][0]).toContain("--fs: calc(");
    expect(onChange).not.toHaveBeenCalled();

    // 防抖结束后恰好提交一次 —— 不是每拖一格一次。
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange.mock.calls[0][0]).toMatchObject({
      font_scale: "standard",
      format_config: { font_scale_adjust: expect.any(Number) },
    });
    // 14px 上调 3 格 → 14.3px，系数 14.3 / 14 ≈ 1.021。
    expect(Number(onChange.mock.calls[0][0].format_config.font_scale_adjust)).toBeCloseTo(1.021, 2);
  });

  it("从大字号往下拖会就近落到标准档并带小于 1 的系数", async () => {
    const onChange = renderControls({
      layout: { ...DEFAULT_LAYOUT, font_scale: "large" },
    });
    const slider = await screen.findByRole("slider");

    // 15.5px 往下 18 格 → 13.7px，最近档是标准档（14），系数 13.7 / 14 ≈ 0.979（< 1）。
    for (let i = 0; i < 18; i += 1) pressArrow(slider, "ArrowLeft");

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange.mock.calls[0][0]).toMatchObject({ font_scale: "standard" });
    expect(Number(onChange.mock.calls[0][0].format_config.font_scale_adjust)).toBeLessThan(1);
  });

  it("拖动全程零网络：fetch 与 previewResumeTemplate 一次都没被调用", async () => {
    // 直接盯住网络入口本身，而不是"某个回调没被调"：将来若有人在拖动处理里塞一句
    // 裸 fetch / 预览请求，这条断言会立刻红——这是"零网络"最靠得住的说法。
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { ref } = makePreviewRef();
    const onChange = renderControls({ previewRef: ref });

    const slider = await screen.findByRole("slider");
    for (let i = 0; i < 6; i += 1) pressArrow(slider, "ArrowRight");

    // 拖动中：任何网络入口都没被碰过，也没有提交。
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(apiMocks.previewResumeTemplate).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();

    // 松手防抖后：恰好一次提交，且这次提交本身也不走 fetch（由父组件统一落库）。
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(apiMocks.previewResumeTemplate).not.toHaveBeenCalled();
  });

  it("「恢复默认」回到默认档位并清掉字号系数，其它覆盖保留", async () => {
    const { ref, setLiveProbe } = makePreviewRef();
    const onChange = renderControls({
      layout: {
        ...DEFAULT_LAYOUT,
        font_scale: "large",
        format_config: { font_scale_adjust: 0.95, accent: "#123456" },
      },
      previewRef: ref,
    });

    fireEvent.click(await screen.findByRole("button", { name: "恢复默认字号" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toMatchObject({
      font_scale: TEMPLATE_CATALOG.defaults.font_scale,
      format_config: { accent: "#123456" },
    });
    expect(onChange.mock.calls[0][0].format_config).not.toHaveProperty("font_scale_adjust");
    expect(setLiveProbe).toHaveBeenCalledWith("");
  });
});

describe("ResumeLayoutControls · 板块顺序", () => {
  async function openOrderPanel() {
    fireEvent.click(await screen.findByRole("button", { name: "调整简历板块顺序" }));
    const list = await screen.findByRole("list", { name: "简历板块顺序" });
    return list;
  }

  it("弹层里按当前顺序列出全部分区", async () => {
    renderControls();
    const list = await openOrderPanel();
    const labels = Array.from(list.querySelectorAll(".resume-section-order-label")).map(
      (node) => node.textContent,
    );
    expect(labels).toEqual([
      "个人总结",
      "教育经历",
      "实习/工作经历",
      "校园经历",
      "项目经历",
      "专业技能",
      "荣誉奖项",
    ]);
  });

  it("上移会以完整排列写入 format_config.section_order", async () => {
    const onChange = renderControls();
    await openOrderPanel();

    // 把「项目经历」（默认第 5 位）上移一格。
    fireEvent.click(screen.getByRole("button", { name: "把项目经历上移" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const nextLayout = onChange.mock.calls[0][0] as ResumeLayout;
    expect(nextLayout.format_config?.section_order).toEqual([
      "summary",
      "education",
      "experience",
      "projects",
      "campus_experience",
      "skills",
      "awards",
    ]);
    // 其余版式覆盖不被这次操作清掉。
    expect(nextLayout.template).toBe("classic");
  });

  it("已调整时按钮会标出来，「恢复默认」清掉 section_order 但保留其它覆盖", async () => {
    const onChange = renderControls({
      layout: {
        ...DEFAULT_LAYOUT,
        format_config: {
          accent: "#123456",
          section_order: [
            "projects",
            "summary",
            "education",
            "experience",
            "campus_experience",
            "skills",
            "awards",
          ],
        },
      },
    });

    expect(await screen.findByRole("button", { name: "调整简历板块顺序" })).toHaveTextContent(
      "顺序·已调整",
    );

    await openOrderPanel();
    // 精确匹配：工具条上还有一个「恢复默认字号」按钮，用正则会撞车。
    fireEvent.click(screen.getByRole("button", { name: "恢复默认" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const nextLayout = onChange.mock.calls[0][0] as ResumeLayout;
    expect(nextLayout.format_config).not.toHaveProperty("section_order");
    // accent 是用户自己的覆盖，不动它。
    expect(nextLayout.format_config).toMatchObject({ accent: "#123456" });
  });
});
