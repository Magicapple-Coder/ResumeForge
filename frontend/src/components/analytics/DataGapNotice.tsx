/** 数据缺口提示：**整页唯一的"这张图为什么是空的"实现**。
 *
 * 存在的理由是诚实。图表只统计有值的记录，此时若画一张全零的图，用户会读成
 * "这几个月真的一份没投"，而事实是那些记录**没填日期**——一个会撒谎的零比一句
 * "没数据"糟糕得多（同类先例：`TrackerPage` 计数为 0 时不画条形、PDF 导出的
 * `overflow` 标志不许说谎）。
 *
 * `missing` 为 0 时**返回 null**：没有缺口就一个字都不显示，不留空占位。 */
import { Typography } from "antd";
import type { ReactNode } from "react";

interface Props {
  /** 缺失的数量。为 0 时整个组件不渲染。 */
  missing: number;
  /** 缺的是什么，例如"未填投递日期"。 */
  label: string;
  /** 可选：有值的数量，用来把话说全（"12 条中 3 条未计入"）。 */
  available?: number;
  /** 可选：去补数据/看明细的入口。 */
  action?: ReactNode;
}

export default function DataGapNotice({ missing, label, available, action }: Props) {
  if (missing <= 0) return null;
  return (
    <Typography.Text type="warning" className="analytics-gap-notice">
      有 {missing} 条{label}，未计入下方图表
      {typeof available === "number" ? `（共 ${available + missing} 条记录）` : ""}
      {action ? <> {action}</> : null}
    </Typography.Text>
  );
}
