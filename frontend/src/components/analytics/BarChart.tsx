/** 投递趋势柱状图：自绘 SVG，不引 echarts/antv/plots。
 *
 * 每个自然月一根柱子，高度与投递数量成正比（相对最大值）。只负责画，
 * 月度数据由后端 ``/api/analytics/dashboard`` 的 ``trend`` 下发。
 */
import type { TrendPoint } from "../../types";

interface Props {
  points: TrendPoint[];
}

export default function BarChart({ points }: Props) {
  const max = Math.max(1, ...points.map((point) => point.count));
  const width = 620;
  const height = 240;
  const padding = { top: 24, right: 12, bottom: 32, left: 12 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const slot = points.length ? chartWidth / points.length : chartWidth;
  const barWidth = Math.min(48, slot * 0.6);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="投递趋势">
      {points.map((point, index) => {
        const barHeight = Math.round((point.count / max) * chartHeight);
        const x = padding.left + index * slot + (slot - barWidth) / 2;
        const y = padding.top + chartHeight - barHeight;
        return (
          <g key={point.month}>
            <rect x={x} y={y} width={barWidth} height={barHeight} rx={4} fill="#1677ff" />
            {point.count > 0 && (
              <text x={x + barWidth / 2} y={y - 6} textAnchor="middle" fontSize={12} fill="#333">
                {point.count}
              </text>
            )}
            <text
              x={x + barWidth / 2}
              y={height - 10}
              textAnchor="middle"
              fontSize={12}
              fill="#555"
            >
              {point.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
