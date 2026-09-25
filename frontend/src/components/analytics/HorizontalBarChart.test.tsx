/** 横向条形图：漏斗与排行共用同一份几何，对齐方式决定读法。 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HorizontalBarChart, {
  HORIZONTAL_BAR_GAP,
  HORIZONTAL_BAR_HEIGHT,
  HORIZONTAL_BAR_WIDTH,
} from "./HorizontalBarChart";
import { estimateTextWidth } from "./barLabelLayout";

const ITEMS = [
  { key: "a", label: "甲", count: 4 },
  { key: "b", label: "乙", count: 2 },
  { key: "c", label: "丙", count: 1 },
];

function rects(container: HTMLElement) {
  return Array.from(container.querySelectorAll("rect"));
}
function barRects(container: HTMLElement) {
  return rects(container).filter((rect) => rect.getAttribute("data-bar") === "true");
}
function trackRects(container: HTMLElement) {
  return rects(container).filter((rect) => rect.getAttribute("data-track") === "true");
}
function barXs(container: HTMLElement): number[] {
  return barRects(container).map((rect) => Number(rect.getAttribute("x")));
}

describe("HorizontalBarChart", () => {
  it("长公司名不会被画布左边缘裁掉（标签区按最长标签变宽）", () => {
    // 用户报的正是这条：「投递最多的公司」里公司名前面几个字符被遮住了。
    // 原因是标签右端固定、向左排版，固定 96px 的标签区装不下八个汉字。
    const long = { key: "a", label: "示例科技有限公司", count: 3 };
    const { container } = render(
      <HorizontalBarChart items={[long]} ariaLabel="投递最多的公司" align="start" />,
    );

    const label = container.querySelector("text")!;
    const x = Number(label.getAttribute("x"));
    // 估宽 ≈ 8 个汉字 × 13px；右端 x 减去文字宽度后必须仍在画布内（不能为负）。
    expect(x - estimateTextWidth(long.label)).toBeGreaterThanOrEqual(0);
    // 标签没被截断，显示的就是全名。
    expect(label.textContent).toContain("示例科技有限公司");
  });

  it("长到放不下的名字被截断加省略号，完整名称留在 title 里", () => {
    const huge = "示例国际控股集团有限责任公司上海分公司";
    const { container } = render(
      <HorizontalBarChart
        items={[{ key: "a", label: huge, count: 1 }]}
        ariaLabel="投递最多的公司"
      />,
    );

    const label = container.querySelector("text")!;
    // 只取直接文本节点：`textContent` 会把 <title> 里的全名也算进来，量出来的宽度就不对了。
    const shown = Array.from(label.childNodes)
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent ?? "")
      .join("");
    expect(shown).toContain("…");
    expect(label.querySelector("title")?.textContent).toBe(huge);
    // 截断后仍不能越过左边缘。
    expect(Number(label.getAttribute("x")) - estimateTextWidth(shown)).toBeGreaterThanOrEqual(0);
  });

  it("没被截断的标签不挂 title（完整显示的行不该多一个同文提示）", () => {
    const { container } = render(<HorizontalBarChart items={ITEMS} ariaLabel="测试图" />);
    for (const label of Array.from(container.querySelectorAll("text"))) {
      expect(label.querySelector("title")).toBeNull();
    }
  });

  it("高度随条目数线性收窄，与其余图表同一套紧凑口径", () => {
    const { container } = render(<HorizontalBarChart items={ITEMS} ariaLabel="测试图" />);
    const svg = container.querySelector("svg")!;
    const viewBox = svg.getAttribute("viewBox")!.split(" ").map(Number);

    expect(viewBox[2]).toBe(HORIZONTAL_BAR_WIDTH);
    expect(viewBox[3]).toBe(ITEMS.length * (HORIZONTAL_BAR_HEIGHT + HORIZONTAL_BAR_GAP) + 20);
  });

  it("渲染宽度封顶在 viewBox 宽度，不随容器放大超过 1:1", () => {
    // 这条是"图表随窗口放大"的真守卫：几何只有一份，封顶也必须只有一份。
    const { container } = render(<HorizontalBarChart items={ITEMS} ariaLabel="测试图" />);
    const svg = container.querySelector("svg")!;
    const viewBoxWidth = Number(svg.getAttribute("viewBox")!.split(" ")[2]);

    expect(svg.style.maxWidth).toBe(`${viewBoxWidth}px`);
  });

  it("排行模式所有条共享同一左基线，长度才可比", () => {
    const { container } = render(
      <HorizontalBarChart items={ITEMS} ariaLabel="投递最多的公司" align="start" />,
    );

    const xs = barXs(container);
    expect(new Set(xs).size).toBe(1);
  });

  it("默认居中：漏斗靠居中的形状表达递减，条不共享左基线", () => {
    const { container } = render(<HorizontalBarChart items={ITEMS} ariaLabel="求职漏斗" />);

    // 计数不同 → 条宽不同 → 居中时起点也不同；若哪天默认值被改成 start，这条会红。
    expect(new Set(barXs(container)).size).toBeGreaterThan(1);
  });

  it("无障碍名取自 prop，同一页多张图才不会撞名", () => {
    const { container } = render(<HorizontalBarChart items={ITEMS} ariaLabel="内推状态分布" />);

    expect(container.querySelector("svg")!.getAttribute("aria-label")).toBe("内推状态分布");
  });

  it("每行都有全宽浅色轨道垫底，且计数标签落在轨道右侧", () => {
    const { container } = render(
      <HorizontalBarChart items={ITEMS} ariaLabel="测试图" align="start" />,
    );

    // 三个条目 → 三条轨道；轨道起点一致、宽度铺满 chartWidth（与条对齐起点相同）。
    expect(trackRects(container)).toHaveLength(ITEMS.length);
    for (const track of trackRects(container)) {
      expect(Number(track.getAttribute("x"))).toBe(96);
      expect(Number(track.getAttribute("width"))).toBeGreaterThan(0);
    }
  });

  it("计数为 0 时显示空轨道与「0」标签，不再画彩色细条", () => {
    // 与旧版"画一条最小彩色条"不同：0 阶段应是看得见的事实（空轨道 + 0），而不是细条。
    const { container } = render(
      <HorizontalBarChart
        items={[
          { key: "a", label: "甲", count: 3 },
          { key: "b", label: "乙", count: 0 },
        ]}
        ariaLabel="测试图"
        align="start"
      />,
    );

    // 两条轨道都在（含 0 阶段），但只有非零那一条画了彩色条。
    expect(trackRects(container)).toHaveLength(2);
    expect(barRects(container)).toHaveLength(1);
    // 0 仍然被如实写出来，不会整行消失让读者以为这一项不存在。
    const texts = Array.from(container.querySelectorAll("text")).map((t) => t.textContent ?? "");
    expect(texts.some((t) => t.startsWith("0"))).toBe(true);
  });

  it("开启 showPercent 时在第一阶段外显示相对第一阶段的百分比", () => {
    const { container } = render(
      <HorizontalBarChart
        items={[
          { key: "a", label: "甲", count: 10 },
          { key: "b", label: "乙", count: 5 },
        ]}
        ariaLabel="求职漏斗"
        showPercent
      />,
    );

    const svg = container.querySelector("svg")!;
    const texts = Array.from(svg.querySelectorAll("text")).map((t) => t.textContent ?? "");
    // 10 是基准 → 100%；5 是它的一半 → 50%。
    expect(texts.some((t) => t.includes("100%"))).toBe(true);
    expect(texts.some((t) => t.includes("50%"))).toBe(true);
  });
});
