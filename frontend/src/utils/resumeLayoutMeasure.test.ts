/**
 * 版面测量：元素筛选与算术。
 *
 * jsdom 不会真的排版，所以这里把每个元素的 `getBoundingClientRect` 与控制台的
 * computed style 打桩，专门验证**筛选规则**（哪些元素算正文）与**算式**（减去 padding、
 * 除以页数）——这两件事出错的后果是"填充度算错"，而界面上完全看不出来。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  measureResumeLayout,
  overflowHeightFor,
  pagesNeededFor,
  type LayoutMeasure,
} from "./resumeLayoutMeasure";

interface Box {
  top?: number;
  bottom: number;
  width?: number;
  height?: number;
}

/** 元素 → 打桩的样式；测量代码只读这一个字典，不必反复 mock getComputedStyle。 */
const stylesByElement = new WeakMap<Element, Record<string, string>>();
const boxesByElement = new WeakMap<Element, Box>();

const DEFAULT_STYLE = {
  paddingTop: "0px",
  paddingBottom: "0px",
  marginBottom: "0px",
  display: "block",
  visibility: "visible",
  position: "static",
};

/** 给元素打桩：矩形与计算样式都由调用方指定。 */
function stubElement(element: Element, box: Box, styles: Record<string, string> = {}): void {
  boxesByElement.set(element, box);
  stylesByElement.set(element, { ...DEFAULT_STYLE, ...styles });

  element.getBoundingClientRect = () => {
    const current = boxesByElement.get(element) ?? box;
    return {
      top: current.top ?? 0,
      bottom: current.bottom,
      left: 0,
      right: current.width ?? 100,
      width: current.width ?? 100,
      height: current.height ?? current.bottom - (current.top ?? 0),
      x: 0,
      y: current.top ?? 0,
      toJSON: () => ({}),
    } as DOMRect;
  };
}

beforeEach(() => {
  // jsdom 不做真实排版，computed style 也拿不到有意义的数值，所以整段换掉。
  vi.spyOn(window, "getComputedStyle").mockImplementation(
    (target: Element) =>
      (stylesByElement.get(target) ?? DEFAULT_STYLE) as unknown as CSSStyleDeclaration,
  );
});

function resetDom(): void {
  document.body.innerHTML = "";
}

afterEach(() => {
  vi.restoreAllMocks();
  resetDom();
});

function buildPage(): { body: HTMLElement; text: HTMLElement } {
  resetDom();
  const text = document.createElement("p");
  text.textContent = "负责检索接口的实现与联调";
  document.body.appendChild(text);
  return { body: document.body, text };
}

describe("measureResumeLayout", () => {
  it("measures the last block of body text against the page content box", () => {
    const { body, text } = buildPage();
    // 页高 1123，上下各 53 的页边距 → 一页可用 1017。
    stubElement(body, { top: 0, bottom: 1123 }, { paddingTop: "53px", paddingBottom: "53px" });
    stubElement(text, { top: 53, bottom: 561.5 });

    const measure = measureResumeLayout(document, 1);
    expect(measure).not.toBeNull();
    expect(measure!.pageContentHeight).toBeCloseTo(1017, 5);
    expect(measure!.usedHeight).toBeCloseTo(508.5, 5);
  });

  it("divides the content box by the page count", () => {
    const { body, text } = buildPage();
    stubElement(body, { top: 0, bottom: 2246 }, { paddingTop: "53px", paddingBottom: "53px" });
    stubElement(text, { top: 53, bottom: 1000 });

    const measure = measureResumeLayout(document, 2);
    expect(measure!.pageContentHeight).toBeCloseTo((2246 - 106) / 2, 5);
  });

  it("counts the last element's bottom margin", () => {
    const { body, text } = buildPage();
    stubElement(body, { top: 0, bottom: 1123 }, { paddingTop: "53px", paddingBottom: "53px" });
    stubElement(text, { top: 53, bottom: 500 }, { marginBottom: "18px" });

    // 下外边距也是占掉的高度：不算进去会让排版看起来还差一截就溢出了。
    expect(measureResumeLayout(document, 1)!.usedHeight).toBeCloseTo(465, 5);
  });

  it("ignores empty containers so a stray wrapper is not counted as content", () => {
    const { body, text } = buildPage();
    const wrapper = document.createElement("div");
    document.body.appendChild(wrapper);
    stubElement(body, { top: 0, bottom: 1123 }, { paddingTop: "53px", paddingBottom: "53px" });
    stubElement(text, { top: 53, bottom: 300 });
    // 一个只带下边距、没有任何文字的空 div：不能因为它把版面算得更满。
    stubElement(wrapper, { top: 53, bottom: 900 }, { marginBottom: "40px" });

    expect(measureResumeLayout(document, 1)!.usedHeight).toBeCloseTo(247, 5);
  });

  it("ignores hidden elements", () => {
    const { body, text } = buildPage();
    const hidden = document.createElement("p");
    hidden.textContent = "被隐藏的内容";
    document.body.appendChild(hidden);
    stubElement(body, { top: 0, bottom: 1123 }, { paddingTop: "53px", paddingBottom: "53px" });
    stubElement(text, { top: 53, bottom: 300 });
    stubElement(hidden, { top: 53, bottom: 1100 }, { display: "none" });

    expect(measureResumeLayout(document, 1)!.usedHeight).toBeCloseTo(247, 5);
  });

  it("temporarily removes the fit transform before measuring", () => {
    const { body, text } = buildPage();
    stubElement(body, { top: 0, bottom: 1123 }, { paddingTop: "53px", paddingBottom: "53px" });
    stubElement(text, { top: 53, bottom: 400 });
    // 预览会把溢出内容整体 scale 压进页面；带着 transform 量出来的坐标与未变换的
    // padding 混在一起会完全对不上，所以测量期间必须摘掉、量完还原。
    body.style.transform = "scale(0.8)";

    measureResumeLayout(document, 1);
    expect(body.style.transform).toBe("scale(0.8)");
  });

  it("returns null when the page box is degenerate", () => {
    const { body } = buildPage();
    // 页面高度量成 0（还没渲染完就量了）时不能除零。
    stubElement(body, { top: 0, bottom: 0 }, { paddingTop: "53px", paddingBottom: "53px" });
    expect(measureResumeLayout(document, 1)).toBeNull();
    expect(measureResumeLayout(document, 0)).toBeNull();
  });
});

function measure(usedHeight: number, pageContentHeight: number, pageLimit: number): LayoutMeasure {
  return { usedHeight, pageContentHeight, pageLimit };
}

describe("pagesNeededFor", () => {
  it("内容恰好放满一页时算一页", () => {
    expect(pagesNeededFor(measure(1000, 1000, 1))).toBe(1);
  });

  it("多出一丁点就算下一页", () => {
    expect(pagesNeededFor(measure(1001, 1000, 1))).toBe(2);
  });

  it("内容为空时至少算一页", () => {
    expect(pagesNeededFor(measure(0, 1000, 1))).toBe(1);
  });

  it("页面内容高度非法时回退到上限页数", () => {
    expect(pagesNeededFor(measure(500, 0, 2))).toBe(2);
  });
});

describe("overflowHeightFor", () => {
  it("放得下时返回 0", () => {
    expect(overflowHeightFor(measure(900, 1000, 1))).toBe(0);
    expect(overflowHeightFor(measure(2000, 1000, 2))).toBe(0);
  });

  it("超出时返回多出的高度（与 pageContentHeight 同单位）", () => {
    expect(overflowHeightFor(measure(1300, 1000, 1))).toBe(300);
    expect(overflowHeightFor(measure(2500, 1000, 2))).toBe(500);
  });
});
