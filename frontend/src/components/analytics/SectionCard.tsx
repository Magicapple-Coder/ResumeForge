/** 分区块主题的容器：一张卡讲一件事。
 *
 * `description` 是**口径说明**——把"这个数字是怎么算的"写在数字旁边，而不是藏进
 * Tooltip。本仓库一贯的做法是把话说出来（对比 `AtsCheckPanel` 的强制免责声明）。 */
import { Card, Typography } from "antd";
import type { CSSProperties, ReactNode } from "react";

interface Props {
  title: string;
  description?: string;
  extra?: ReactNode;
  children: ReactNode;
  style?: CSSProperties;
}

export default function SectionCard({ title, description, extra, children, style }: Props) {
  return (
    <Card
      title={title}
      extra={extra}
      className="analytics-section"
      style={{ marginTop: 16, ...style }}
    >
      {description ? (
        <Typography.Text type="secondary" className="analytics-section-note">
          {description}
        </Typography.Text>
      ) : null}
      {children}
    </Card>
  );
}
