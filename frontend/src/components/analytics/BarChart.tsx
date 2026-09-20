/** 柱状图：自绘 SVG，不引 echarts/antv/plots。
 *
 * 每个数据点一根柱子，高度与计数成正比（相对最大值）。**通用**而不是只认月度趋势——
 * "近 N 个月投递趋势"和"周内投递分布"是同一套几何，各写一张图会让 `maxWidth` 封顶
 * 和高度公式散成两份。只负责画，数据由后端 ``/api/analytics/dashboard`` 下发。
 */

export interface BarPoint {
  /** 面向展示的短标签（如 "9月"、"周一"）。 */
  label: string;
  count: number;
  /** React key；缺省用 label（同图内 label 唯一时够用）。 */
  key?: string;
}

interface Props {
  points: BarPoint[];
  /** 无障碍名。**每张图必须给不同的一条**，否则读屏会撞名、测试也分不清是哪张图。 */
  ariaLabel: string;
}

export default function BarChart({ points, ariaLabel }: Props) {
  const max = Math.max(1, ...points.map((point) => point.count));
  const width = 620;
  // 紧凑：整体高度 170（原 240），上下内边距同步收窄，趋势图下方空白明显减少，
  // 与漏斗图、整页卡片更协调；月份/计数标签字号保持 12，仍清晰可读。
  const height = 170;
  const padding = { top: 18, right: 12, bottom: 30, left: 12 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const slot = points.length ? chartWidth / points.length : chartWidth;
  const barWidth = Math.min(48, slot * 0.6);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      role="img"
      aria-label={ariaLabel}
      // 同 FunnelChart：`width="100%"` 会按「容器宽 ÷ 620」把整张图放大，宽屏下 12px 的
      // 月份标签和柱宽都被成倍撑开。maxWidth 把倍率封顶在 1:1，宽屏不再放大。
      style={{ maxWidth: width, display: "block", margin: "0 auto" }}
    >
      {points.map((point, index) => {
        const barHeight = Math.round((point.count / max) * chartHeight);
        const x = padding.left + index * slot + (slot - barWidth) / 2;
        const y = padding.top + chartHeight - barHeight;
        return (
          <g key={point.key ?? point.label}>
            <rect x={x} y={y} width={barWidth} height={barHeight} rx={4} fill="#1677ff" />
            {/* 计数为 0 时不画数字：留一个孤零零的「0」看着像渲染坏了。 */}
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
