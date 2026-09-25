/** 求职漏斗：自绘 SVG，不引 echarts/antv/plots。
 *
 * 每个阶段一条**居中**的横条，宽度与计数成正比（相对最大值）——"漏斗形状"本身就是信息，
 * 所以走居中对齐而不是共享左基线。几何与封顶都在 :mod:`HorizontalBarChart` 里（公司排行
 * 用的是同一份），这里只负责"给每一阶段配一个颜色"和开启"相对第一阶段的百分比"。
 *
 * 每个阶段使用独立的语义色：漏斗的形状表达数量递减，颜色帮助用户快速定位阶段。
 *
 * 只负责画，漏斗的阶段顺序与口径由后端 ``/api/analytics/dashboard`` 下发（见
 * services/analytics.py）。
 */
import type { FunnelStage } from "../../types";
import HorizontalBarChart from "./HorizontalBarChart";

const STAGE_COLORS = ["#8c8c8c", "#5b8ff9", "#61ddaa", "#f6bd16", "#7262fd", "#f08bb4"];

interface Props {
  stages: FunnelStage[];
}

export default function FunnelChart({ stages }: Props) {
  const firstKey = stages[0]?.status;
  return (
    <HorizontalBarChart
      items={stages.map((stage) => ({
        key: stage.status,
        label: stage.label,
        count: stage.count,
      }))}
      ariaLabel="求职漏斗"
      align="center"
      showPercent
      colorFor={(key) => {
        const index = stages.findIndex((stage) => stage.status === key);
        return key === firstKey
          ? STAGE_COLORS[0]
          : STAGE_COLORS[Math.max(1, index) % STAGE_COLORS.length];
      }}
    />
  );
}
