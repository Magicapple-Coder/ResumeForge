/**
 * 展示模型从图片里读到的文字。
 *
 * 这不是装饰：图片识别的字段是锚定在**模型自己抄录的文字**上的，那只能证明字段与
 * 抄录一致，不能证明抄录本身忠实于截图。所以必须让用户能一眼核对它到底读到了什么，
 * 默认收起但始终可达。
 */

import { Collapse, Typography } from "antd";

export default function RecognizedTextField({ text }: { text: string }) {
  if (!text.trim()) return null;

  return (
    <Collapse
      size="small"
      ghost
      className="recognized-text"
      items={[
        {
          key: "recognized",
          label: "查看模型识别到的原文（请对照截图核对）",
          children: (
            <Typography.Paragraph className="recognized-text-body">{text}</Typography.Paragraph>
          ),
        },
      ]}
    />
  );
}
