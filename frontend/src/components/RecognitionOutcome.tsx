/**
 * 识别的结果说明：字段是**谁**认出来的，以及图片识别时模型到底读到了什么。
 *
 * 两件事都必须留在界面上，不能只在识别完成的提示条里出现一次——提示条几秒后消失，
 * 而用户是拿着结果去核对字段的：
 *
 * - **来源**：AI 识别的字段逐条校验过能在你给的内容里找到出处，本地规则只是按模式
 *   匹配，两者可信度不同。看不出区别时，用户会对本地规则的结果也照单全收。
 * - **抄录原文**：图片识别的字段锚定在*模型自己抄录的文字*上，那只能证明字段与抄录
 *   一致，不能证明抄录忠实于截图，所以要把抄录摆出来让人对照。
 */

import { RobotOutlined, ToolOutlined } from "@ant-design/icons";
import { Collapse, Tag, Tooltip, Typography } from "antd";
import type { RecognitionSource } from "../types";

const SOURCE_HINTS: Record<RecognitionSource, { label: string; color: string; hint: string }> = {
  ai: {
    label: "AI 识别",
    color: "blue",
    hint: "由大模型识别，每个字段都校验过能在你给的内容里找到出处；仍请核对后再保存",
  },
  local: {
    label: "本地规则",
    color: "orange",
    hint: "未调用大模型，按内置规则匹配得出；准确度低于 AI 识别，请重点核对后再保存",
  },
};

export default function RecognitionOutcome({
  source,
  text,
}: {
  /** 还没识别过时传 null，此时整块不显示。 */
  source?: RecognitionSource | null;
  text?: string;
}) {
  const hint = source ? SOURCE_HINTS[source] : null;
  const recognized = (text ?? "").trim();
  if (!hint && !recognized) return null;

  return (
    <div className="recognition-outcome">
      {hint && (
        <Tooltip title={hint.hint}>
          <Tag
            className="recognition-source-tag"
            color={hint.color}
            icon={source === "ai" ? <RobotOutlined /> : <ToolOutlined />}
          >
            {hint.label}
          </Tag>
        </Tooltip>
      )}
      {recognized && (
        <Collapse
          size="small"
          ghost
          className="recognized-text"
          items={[
            {
              key: "recognized",
              label: "查看模型识别到的原文（请对照截图核对）",
              children: (
                <Typography.Paragraph className="recognized-text-body">
                  {recognized}
                </Typography.Paragraph>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}
