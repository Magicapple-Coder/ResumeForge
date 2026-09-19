/** 求职漏斗：自绘 SVG，不引 echarts/antv/plots。
 *
 * 每个阶段一条居中的横条，宽度与计数成正比（相对最大值）。只负责画，
 * 漏斗的阶段顺序与口径由后端 ``/api/analytics/dashboard`` 下发（见 services/analytics.py）。
 */
import type { FunnelStage } from "../../types";

const STATUS_COLORS: Record<string, string> = {
  applied: "#8c8c8c",
  screening: "#1677ff",
  assessment: "#13c2c2",
  interview: "#722ed1",
  offer: "#52c41a",
};

interface Props {
  stages: FunnelStage[];
}

export default function FunnelChart({ stages }: Props) {
  const max = Math.max(1, ...stages.map((stage) => stage.count));
  const width = 620;
  const labelWidth = 96;
  const countWidth = 56;
  const chartWidth = width - labelWidth - countWidth;
  const barHeight = 42;
  const gap = 14;
  const height = stages.length * (barHeight + gap) + 24;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="求职漏斗">
      {stages.map((stage, index) => {
        const y = 12 + index * (barHeight + gap);
        const barWidth = Math.max(8, Math.round((stage.count / max) * chartWidth));
        const x = labelWidth + (chartWidth - barWidth) / 2;
        const fill = STATUS_COLORS[stage.status] ?? "#1677ff";
        return (
          <g key={stage.status}>
            <text
              x={labelWidth - 10}
              y={y + barHeight / 2 + 4}
              textAnchor="end"
              fontSize={13}
              fill="#555"
            >
              {stage.label}
            </text>
            <rect x={x} y={y} width={barWidth} height={barHeight} rx={6} fill={fill} opacity={0.9} />
            <text
              x={x + barWidth + 8}
              y={y + barHeight / 2 + 4}
              fontSize={13}
              fill="#333"
              fontWeight={600}
            >
              {stage.count}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
