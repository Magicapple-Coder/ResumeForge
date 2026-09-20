/** 柱状图：自绘 SVG，高度需保持紧凑、与整页协调。 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BarChart from "./BarChart";
import type { TrendPoint } from "../../types/analytics";

const POINTS: TrendPoint[] = [
  { month: "2026-08", label: "8月", count: 3 },
  { month: "2026-09", label: "9月", count: 1 },
];

describe("BarChart", () => {
  it("渲染紧凑的趋势 SVG，整体高度明显收窄", () => {
    const { container } = render(<BarChart points={POINTS} ariaLabel="投递趋势" />);
    const svg = container.querySelector("svg")!;
    const viewBox = svg.getAttribute("viewBox")!.split(" ").map(Number);
    const height = viewBox[3];

    // 之前是 240，这里钉住紧凑高度（压小、去掉大片空白）。
    expect(height).toBeLessThan(200);
    // 月份标签仍渲染。
    expect(svg.textContent).toContain("9月");
  });

  it("渲染宽度封顶在 viewBox 宽度，不随容器放大超过 1:1", () => {
    const { container } = render(<BarChart points={POINTS} ariaLabel="投递趋势" />);
    const svg = container.querySelector("svg")!;
    const viewBoxWidth = Number(svg.getAttribute("viewBox")!.split(" ")[2]);

    // 同 FunnelChart：真正决定观感的是"被放大的倍率"，不是 viewBox 里的数值。
    expect(svg.style.maxWidth).toBe(`${viewBoxWidth}px`);
  });

  it("无障碍名取自 prop，同一页的两张图才不会撞名", () => {
    const { container } = render(<BarChart points={POINTS} ariaLabel="周内投递分布" />);
    const svg = container.querySelector("svg")!;

    // 此前 aria-label 写死「投递趋势」；一旦复用成第二张图（周内分布），
    // 读屏与测试就分不清是哪一张了。
    expect(svg.getAttribute("aria-label")).toBe("周内投递分布");
  });

  it("接受任意 label/count 序列，不绑定月度趋势", () => {
    // 周内分布只有一个 label 与 count，没有 month 字段，也必须能画。
    const { container } = render(
      <BarChart
        points={[
          { key: "0", label: "周一", count: 2 },
          { key: "1", label: "周二", count: 0 },
        ]}
        ariaLabel="周内投递分布"
      />,
    );
    const svg = container.querySelector("svg")!;

    expect(svg.textContent).toContain("周一");
    // 计数为 0 时不画数字，但标签仍要在。
    expect(svg.textContent).toContain("周二");
    expect(svg.textContent).not.toContain("0");
  });
});
