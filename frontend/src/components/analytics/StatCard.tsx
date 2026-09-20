/** 一个统计数字 + 一行说明。整页的指标都走这一个组件，避免 Card/Statistic/副文本
 *  的结构在各处复制十来遍。 */
import { Card, Statistic, Typography } from "antd";
import type { CSSProperties } from "react";

interface Props {
  title: string;
  value: number | string;
  suffix?: string;
  /** 数字下面的一行说明。既是补充数字，也是**口径**（例如"超过 7 天没有更新"）。
   *  留空则不渲染，不会留一个空占位。 */
  hint?: string;
  valueStyle?: CSSProperties;
  /** 外层包一张 Card。顶部指标行用 true；区块内部本来就在 Card 里，用默认 false。 */
  framed?: boolean;
}

export default function StatCard({
  title,
  value,
  suffix,
  hint,
  valueStyle,
  framed = false,
}: Props) {
  const body = (
    <>
      <Statistic title={title} value={value} suffix={suffix} valueStyle={valueStyle} />
      {hint ? <Typography.Text type="secondary">{hint}</Typography.Text> : null}
    </>
  );
  return framed ? <Card>{body}</Card> : body;
}
