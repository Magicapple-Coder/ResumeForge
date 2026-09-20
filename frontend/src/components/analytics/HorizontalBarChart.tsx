/** 横向条形图：自绘 SVG，不引 echarts/antv/plots。
 *
 * 一份几何同时服务两件事——**漏斗**（居中，形状本身是信息）与**排行**（左对齐共享基线，
 * 长度才可比）。抽出来而不是各写一张图，是因为"高度公式"和"`maxWidth` 封顶"这两条
 * **必须只有一处实现**：上次"图表随窗口放大"的修复就是靠这个封顶，散成两份的话下次
 * 只会修到一半。
 *
 * 视觉约定（本轮统一）：每行一条**全宽浅色轨道**（#f0f2f5）垫底，彩色条只表示占比；
 * 计数为 0 的阶段显示"空轨道 + 0 标签"，不再画出难看的彩色细条；条高统一 22px、圆角
 * 统一；计数标签落在轨道右侧，漏斗模式还可选显示"相对第一阶段的百分比"小字。
 *
 * 只负责画。阶段顺序与计数口径由后端 ``/api/analytics/dashboard`` 下发。
 */

export interface HorizontalBarItem {
  key: string;
  label: string;
  count: number;
}

interface Props {
  items: HorizontalBarItem[];
  /** 无障碍名。**每个图表必须给不同的一条**，否则读屏会撞名、测试也分不清是哪张图。 */
  ariaLabel: string;
  /** `center` = 居中（漏斗）；`start` = 左对齐共享基线（排行）。默认居中。 */
  align?: "center" | "start";
  /** 每条的配色；缺省统一用强调蓝。 */
  colorFor?: (key: string) => string;
  /** 是否显示"相对第一阶段的百分比"小字（漏斗默认开，排行不需要）。 */
  showPercent?: boolean;
}

export const HORIZONTAL_BAR_WIDTH = 620;
export const HORIZONTAL_BAR_HEIGHT = 22;
export const HORIZONTAL_BAR_GAP = 12;
export const TRACK_COLOR = "#f0f2f5";
const LABEL_WIDTH = 96;
const COUNT_WIDTH = 56;
const DEFAULT_FILL = "#1677ff";

export default function HorizontalBarChart({
  items,
  ariaLabel,
  align = "center",
  colorFor,
  showPercent = false,
}: Props) {
  const max = Math.max(1, ...items.map((item) => item.count));
  const firstCount = items[0]?.count ?? 0;
  const width = HORIZONTAL_BAR_WIDTH;
  const chartWidth = width - LABEL_WIDTH - COUNT_WIDTH;
  const barHeight = HORIZONTAL_BAR_HEIGHT;
  const gap = HORIZONTAL_BAR_GAP;
  const height = items.length * (barHeight + gap) + 20;
  // 轨道铺满整条可用宽度；彩色条按占比在其中填充（漏斗居中、排行贴左）。
  const trackX = LABEL_WIDTH;
  // 计数标签统一落在轨道右侧，不再随条宽漂移。
  const countX = LABEL_WIDTH + chartWidth + 8;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      role="img"
      aria-label={ariaLabel}
      // viewBox 是图表自己的坐标系，`width="100%"` 会按「容器宽 ÷ 620」把整张图**放大**：
      // 宽屏下 13px 的标签会被放到 40px、22px 的条被放到 90px——这才是"图表明显太大"的来源。
      // maxWidth 把倍率封顶在 1:1，宽屏不再继续放大，窄屏仍按比例缩小；居中避免封顶后贴左。
      style={{ maxWidth: width, display: "block", margin: "0 auto" }}
    >
      {items.map((item, index) => {
        const y = 10 + index * (barHeight + gap);
        const ratio = item.count / max;
        const barWidth = Math.round(ratio * chartWidth);
        const x = align === "start" ? LABEL_WIDTH : LABEL_WIDTH + (chartWidth - barWidth) / 2;
        const fill = colorFor?.(item.key) ?? DEFAULT_FILL;
        const pct =
          showPercent && firstCount > 0 ? Math.round((item.count / firstCount) * 100) : null;
        return (
          <g key={item.key}>
            <text
              x={LABEL_WIDTH - 10}
              y={y + barHeight / 2 + 4}
              textAnchor="end"
              fontSize={13}
              fill="#555"
            >
              {item.label}
            </text>
            {/* 全宽浅色轨道：即使计数为 0 也画出来，让"这一阶段没人"是看得见的事实，
                而不是一条彩色细条或整行消失。 */}
            <rect
              x={trackX}
              y={y}
              width={chartWidth}
              height={barHeight}
              rx={6}
              fill={TRACK_COLOR}
              data-track="true"
            />
            {/* 彩色条只在计数大于 0 时画；0 阶段保留空轨道 + 右侧「0」标签。 */}
            {item.count > 0 && (
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barHeight}
                rx={6}
                fill={fill}
                data-bar="true"
              />
            )}
            <text x={countX} y={y + barHeight / 2 + 4} fontSize={13} fill="#333" fontWeight={600}>
              {item.count}
              {pct !== null && (
                <tspan fontSize={10} fill="#999" dx={4}>
                  {pct}%
                </tspan>
              )}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
