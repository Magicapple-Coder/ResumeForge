/** 求职漏斗：自绘 SVG，不引 echarts/antv/plots。
 *
 * 每个阶段一条**居中**的横条，宽度与计数成正比（相对最大值）——"漏斗形状"本身就是信息，
 * 所以走居中对齐而不是共享左基线。几何与封顶都在 :mod:`HorizontalBarChart` 里（公司排行
 * 用的是同一份），这里只负责"给每一阶段配一个颜色"和开启"相对第一阶段的百分比"。
 *
 * 配色统一：除第一阶段（已投递总量，作为基准）用中性灰外，其余阶段统一强调蓝——漏斗
 * 靠"居中递减的形状"表达信息，不必每段一个色。
 *
 * 只负责画，漏斗的阶段顺序与口径由后端 ``/api/analytics/dashboard`` 下发（见
 * services/analytics.py）。
 */
import type { FunnelStage } from "../../types";
import HorizontalBarChart from "./HorizontalBarChart";

const FIRST_STAGE_FILL = "#8c8c8c";
const DEFAULT_FILL = "#1677ff";

interface Props {
  stages: FunnelStage[];
}

export default function FunnelChart({ stages }: Props) {
  // 第一阶段是总量基准，用中性灰；其余阶段统一强调蓝，靠居中形状而非颜色区分。
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
      colorFor={(key) => (key === firstKey ? FIRST_STAGE_FILL : DEFAULT_FILL)}
    />
  );
}
