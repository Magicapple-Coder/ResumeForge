/** 区块里的一张图 + 它的小标题，装在一个浅色面板里。
 *
 * 为什么要有这一层：求职统计页每张卡里可能并排放两三张图，而这些图此前有的有小标题、
 * 有的没有（漏斗、趋势、周内分布就没有），读者看到的是"一整片图"，分不清哪张是哪张，
 * 也不知道边界在哪——用户的原话是"各个图的界限不太分明"。
 *
 * 统一成"浅色面板 + 左侧小标题"之后：图与图的边界由面板边框给出，图叫什么由小标题给出，
 * 不必再靠间距去猜。`hint` 放口径说明（例如"按投递日期统计"），与标题同一行右对齐。
 */
import { Typography } from "antd";
import type { ReactNode } from "react";

interface Props {
  title: string;
  /** 这张图的统计口径；没有就不显示，不要为凑格式写废话。 */
  hint?: string;
  children: ReactNode;
}

export default function ChartBlock({ title, hint, children }: Props) {
  return (
    <section className="analytics-chart-block" aria-label={title}>
      <div className="analytics-chart-block-head">
        <Typography.Text strong className="analytics-chart-block-title">
          {title}
        </Typography.Text>
        {hint ? (
          <Typography.Text type="secondary" className="analytics-chart-block-hint">
            {hint}
          </Typography.Text>
        ) : null}
      </div>
      {children}
    </section>
  );
}
