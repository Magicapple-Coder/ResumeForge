/**
 * 「只编辑选中的这一部分」：在预览里点中某一栏后，**只**改那一处。
 *
 * 与「手动调整」（整份简历的编辑器）分开是刻意的：
 * - 预览里点哪儿改哪儿，是最常见的动作（"这条要点补个数字"），弹一个只有这一栏的窗口
 *   最省事，也不会让人在十几个标签页里重新找一遍刚才点的地方；
 * - 要通读、要跨栏改、要用写作增强，再走「手动调整」那个完整编辑器。
 *
 * 保存走的是与完整编辑器同一个回调（父组件的 `onSaved`），所以两条路的落库行为一致。
 */
import { SaveOutlined } from "@ant-design/icons";
import { App, Button, Input, Modal, Space, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import type { ResumeContent } from "../../types";
import {
  describeResumeFieldPath,
  readResumeValueByPath,
  writeResumeValueByPath,
} from "../../utils/resumeFieldPath";
import FieldRewritePanel from "../resume-editor/FieldRewritePanel";

interface Props {
  open: boolean;
  resumeId: number;
  content: ResumeContent;
  /** 选中的那一栏（`data-resume-path` 写法）。 */
  path: string | null;
  onClose: () => void;
  /** 保存整份内容（与完整编辑器同一个回调）。 */
  onSaved: (content: ResumeContent) => Promise<void>;
}

/** 多行文本才用 TextArea；姓名、电话这类短字段用单行。 */
const MULTILINE_PATHS = new Set(["summary", "job_intent"]);

export default function ResumeFieldQuickEditModal({
  open,
  resumeId,
  content,
  path,
  onClose,
  onSaved,
}: Props) {
  const { message } = App.useApp();
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<ResumeContent>(content);
  const [saving, setSaving] = useState(false);

  // 每次打开/换栏都从简历当前值重新取：不要沿用上一栏的残留文本。
  useEffect(() => {
    if (!open || !path) return;
    setDraft(content);
    const value = readResumeValueByPath(content, path);
    // 一段经历的"工作内容 / 要点"是字符串数组：按行编辑，一行一条。
    setText(Array.isArray(value) ? value.join("\n") : typeof value === "string" ? value : "");
  }, [open, path, content]);

  const isList = useMemo(() => {
    if (!path) return false;
    return Array.isArray(readResumeValueByPath(content, path));
  }, [content, path]);

  if (!path) return null;

  const label = describeResumeFieldPath(path, content);
  const multiline = isList || MULTILINE_PATHS.has(path.split(".")[0]);

  const save = async () => {
    setSaving(true);
    try {
      const nextValue = isList ? text.split("\n").filter((line) => line.trim() !== "") : text;
      const next = writeResumeValueByPath(draft, path, nextValue);
      await onSaved(next);
      message.success("已保存这一栏");
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败，请稍后重试");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`编辑：${label}`}
      open={open}
      onCancel={onClose}
      width={620}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={() => void save()}
          >
            保存这一栏
          </Button>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        这里只改你选中的这一处，其它内容不受影响。想通读整份简历再改，用底部的「手动调整」。
      </Typography.Paragraph>

      <Typography.Text strong>{isList ? "内容（一行一条）" : "内容"}</Typography.Text>
      {multiline ? (
        <Input.TextArea
          value={text}
          onChange={(event) => setText(event.target.value)}
          autoSize={{ minRows: 3, maxRows: 10 }}
          aria-label="这一栏的内容"
          style={{ marginTop: 6 }}
        />
      ) : (
        <Input
          value={text}
          onChange={(event) => setText(event.target.value)}
          aria-label="这一栏的内容"
          style={{ marginTop: 6 }}
        />
      )}

      {/* 同一套「按我的要求改这一栏」：它写入的是上面的文本框，仍需点「保存这一栏」才落库。 */}
      <div style={{ marginTop: 16 }}>
        <FieldRewritePanel
          resumeId={resumeId}
          content={draft}
          path={path}
          onChange={(next) => {
            setDraft(next);
            const value = readResumeValueByPath(next, path);
            setText(
              Array.isArray(value) ? value.join("\n") : typeof value === "string" ? value : "",
            );
          }}
        />
      </div>
    </Modal>
  );
}
