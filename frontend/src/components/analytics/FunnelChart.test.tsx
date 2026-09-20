/** 漏斗图：自绘 SVG，高度需保持紧凑、与整页协调。 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FunnelChart from "./FunnelChart";
import type { FunnelStage } from "../../types/analytics";

const STAGES: FunnelStage[] = [
  { status: "applied", label: "已投递", count: 10 },
  { status: "screening", label: "筛选中", count: 8 },
  { status: "assessment", label: "测评/笔试", count: 5 },
  { status: "interview", label: "面试", count: 3 },
  { status: "offer", label: "Offer", count: 1 },
];

describe("FunnelChart", () => {
  it("渲染紧凑的 SVG，整体高度随阶段数收窄", () => {
    const { container } = render(<FunnelChart stages={STAGES} />);
    const svg = container.querySelector("svg")!;
    const viewBox = svg.getAttribute("viewBox")!.split(" ").map(Number);
    const height = viewBox[3];

    // 5 个阶段整体高度应明显低于早期 300+ 的取值（紧凑、不占一大片）。
    expect(height).toBeLessThan(260);
    // 每条阶段的标签都渲染出来了，没被挤没。
    expect(svg.querySelectorAll("text").length).toBeGreaterThanOrEqual(STAGES.length);
  });

  it("渲染宽度封顶在 viewBox 宽度，不随容器放大超过 1:1", () => {
    const { container } = render(<FunnelChart stages={STAGES} />);
    const svg = container.querySelector("svg")!;
    const viewBoxWidth = Number(svg.getAttribute("viewBox")!.split(" ")[2]);

    // 这条才是"图表明显太大"的真守卫：`width="100%"` 会按「容器宽 ÷ viewBox 宽」整体放大，
    // 宽屏下 13px 的标签被放到 40px、28px 的条被放到 90px。只断言 viewBox 数值的话，
    // 被放大的倍率怎么变都测不出来——上一轮的"紧凑"改动正是这样通过的。
    expect(svg.style.maxWidth).toBe(`${viewBoxWidth}px`);
  });
});
