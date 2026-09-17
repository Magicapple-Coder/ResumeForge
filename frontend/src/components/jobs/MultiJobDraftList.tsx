/**
 * 一次粘贴里识别出多份招聘信息时的确认面板。
 *
 * 为什么需要它：识别出多份不代表用户想全都要（可能是从聊天记录里整段复制的），
 * 所以默认全勾选、但允许取消；每条都显示"来自哪一段"的原文摘要，用户能一眼看出
 * 拆分对不对——这比直接静默保存成 5 个岗位好得多。
 */
import { FileTextOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Checkbox, Space, Tag, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";
import type { ParsedJobDraft } from "../../types";

interface Props {
  drafts: ParsedJobDraft[];
  saving: boolean;
  engineLabel: string;
  onSave: (drafts: ParsedJobDraft[]) => void;
  /** 只处理第一条：填进表单里让用户继续编辑。 */
  onEditSingle: (draft: ParsedJobDraft) => void;
  onCancel: () => void;
}

function draftTitle(draft: ParsedJobDraft, index: number): string {
  return draft.title?.trim() || draft.company?.trim() || `未命名岗位 ${index + 1}`;
}

function excerpt(text: string): string {
  const cleaned = text.replace(/\s+/g, " ").trim();
  return cleaned.length > 90 ? `${cleaned.slice(0, 90)}…` : cleaned;
}

export default function MultiJobDraftList({
  drafts,
  saving,
  engineLabel,
  onSave,
  onEditSingle,
  onCancel,
}: Props) {
  const [selected, setSelected] = useState<number[]>(() => drafts.map((_, index) => index));

  // 识别结果换了（用户又点了一次识别）就重置勾选，避免沿用上一次的下标。
  useEffect(() => {
    setSelected(drafts.map((_, index) => index));
  }, [drafts]);

  const toggle = (index: number, checked: boolean) => {
    setSelected((current) =>
      checked
        ? [...new Set([...current, index])].sort((a, b) => a - b)
        : current.filter((i) => i !== index),
    );
  };

  const chosen = drafts.filter((_, index) => selected.includes(index));

  return (
    <div className="multi-draft-list">
      <Alert
        type="info"
        showIcon
        message={`识别出 ${drafts.length} 份招聘信息（${engineLabel}）`}
        description="确认拆分是否正确，取消勾选不想保存的那些。保存后它们会各自成为岗位广场里的一条岗位。"
      />

      <Space direction="vertical" style={{ width: "100%", marginTop: 12 }}>
        {drafts.map((draft, index) => (
          <Card
            key={`${index}-${draft.title}-${draft.company}`}
            size="small"
            className="multi-draft-card"
          >
            <div className="multi-draft-card-head">
              <Checkbox
                checked={selected.includes(index)}
                onChange={(event) => toggle(index, event.target.checked)}
              >
                <span className="multi-draft-title">{draftTitle(draft, index)}</span>
              </Checkbox>
              <Tooltip title="只把这一份填进表单，方便逐字段修改后再保存">
                <Button type="link" size="small" onClick={() => onEditSingle(draft)}>
                  单独编辑
                </Button>
              </Tooltip>
            </div>
            <Space size={6} wrap style={{ marginTop: 4 }}>
              {draft.company ? <Tag color="blue">{draft.company}</Tag> : null}
              {draft.location ? <Tag>{draft.location}</Tag> : null}
              {draft.salary ? <Tag color="gold">{draft.salary}</Tag> : null}
              {draft.job_type ? <Tag color="purple">{draft.job_type}</Tag> : null}
              {!draft.description?.trim() ? <Tag color="orange">缺少职位描述</Tag> : null}
            </Space>
            {draft.recognized_text ? (
              <Typography.Paragraph type="secondary" className="multi-draft-excerpt">
                <FileTextOutlined /> 原文：{excerpt(draft.recognized_text)}
              </Typography.Paragraph>
            ) : null}
            {draft.warnings.length > 0 ? (
              <Typography.Text type="warning" className="multi-draft-warning">
                {draft.warnings[0]}
              </Typography.Text>
            ) : null}
          </Card>
        ))}
      </Space>

      <Space wrap style={{ marginTop: 16 }}>
        <Button
          type="primary"
          loading={saving}
          disabled={chosen.length === 0}
          onClick={() => onSave(chosen)}
        >
          保存勾选的 {chosen.length} 份为岗位
        </Button>
        <Button disabled={saving} onClick={onCancel}>
          返回修改原文
        </Button>
      </Space>
    </div>
  );
}
