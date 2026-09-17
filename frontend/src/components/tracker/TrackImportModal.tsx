/**
 * 从通知材料导入进度：粘贴/截图 → 识别预览 → 勾选确认 → 写入。
 *
 * 预览这一步不是走过场：面板上每条都写明"会新增 / 会更新 / 没变化"和原因，用户看的是
 * **会发生什么**，而不是一堆等他自己判断的字段。取消或关闭都不会写任何数据。
 */
import { App, Button, Checkbox, Empty, Input, Modal, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { applyTracks, parseTracks } from "../../api/tracker";
import { useRecognitionFiles } from "../../hooks/useRecognitionFiles";
import RecognitionFileField from "../RecognitionFileField";
import type { TrackMergePreview, TrackRecord } from "../../types";
import { MERGE_ACTION_COLORS, MERGE_ACTION_LABELS, TRACK_STATUS_LABELS } from "../../types";

interface Row {
  key: number;
  checked: boolean;
  preview: TrackMergePreview;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}

export default function TrackImportModal({ open, onClose, onImported }: Props) {
  const { message } = App.useApp();
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [engine, setEngine] = useState<"ai" | "local" | "">("");
  const [busy, setBusy] = useState(false);
  const { files, reading, addFiles, removeFile, clear, onPaste } = useRecognitionFiles();

  // 关闭时清空：否则下次打开会看到上一次的材料和预览，容易误以为已经保存过了。
  useEffect(() => {
    if (open) return;
    setText("");
    setRows([]);
    setNotes([]);
    setEngine("");
    clear();
  }, [open, clear]);

  const recognize = async () => {
    if (!text.trim() && files.length === 0) {
      message.warning("请先粘贴通知内容，或上传截图、文档");
      return;
    }
    setBusy(true);
    try {
      const result = await parseTracks({
        text,
        images: files
          .filter((file) => file.kind === "image")
          .map(({ name, mime_type, data }) => ({ name, mime_type, data })),
        documents: files
          .filter((file) => file.kind === "document")
          .map(({ name, mime_type, data }) => ({ name, mime_type, data })),
      });
      setRows(result.items.map((preview, index) => ({ key: index, checked: true, preview })));
      setNotes(result.notes);
      setEngine(result.parse_engine);
      if (result.items.length === 0) message.info("没有识别出可用的进度记录");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "识别失败");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    const picked = rows.filter((row) => row.checked).map((row) => row.preview.record);
    if (picked.length === 0) {
      message.warning("请至少勾选一条");
      return;
    }
    setBusy(true);
    try {
      const result = await applyTracks(picked as TrackRecord[]);
      // 如实分别报出三种结果：全都说成"已保存"会让用户以为进度确实更新了。
      const parts = [
        result.created ? `新增 ${result.created} 条` : "",
        result.updated ? `更新 ${result.updated} 条` : "",
        result.unchanged ? `${result.unchanged} 条已是最新` : "",
      ].filter(Boolean);
      message.success(parts.join("，") || "已处理");
      onImported();
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title="从通知导入进度"
      width={780}
      onCancel={onClose}
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          {rows.length > 0 && (
            <Button type="primary" loading={busy} onClick={() => void confirm()}>
              确认写入勾选的 {rows.filter((row) => row.checked).length} 条
            </Button>
          )}
        </Space>
      }
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Typography.Text type="secondary">
          把招聘邮件、短信或站内通知的内容粘贴进来（也可以贴截图）。识别结果先给你看"会发生什么"，
          你确认之后才会写入。
        </Typography.Text>
        <Input.TextArea
          rows={6}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onPaste={onPaste}
          placeholder="在这里按 Ctrl+V 可以直接贴截图；纯文字通知直接粘进来即可。"
          disabled={busy}
        />
        <RecognitionFileField
          files={files}
          reading={reading}
          disabled={busy}
          onAddFiles={(incoming) => void addFiles(incoming)}
          onRemove={removeFile}
        />
        <Space>
          <Button type="primary" loading={busy} onClick={() => void recognize()}>
            识别并预览
          </Button>
          {engine && (
            <Tag color={engine === "ai" ? "blue" : "default"}>
              {engine === "ai" ? "AI 识别" : "本地关键词匹配"}
            </Tag>
          )}
        </Space>

        {notes.map((note) => (
          <Typography.Text key={note} type="secondary" className="track-import-note">
            · {note}
          </Typography.Text>
        ))}

        {rows.length === 0 ? (
          <Empty description="还没有识别结果" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div className="track-import-list">
            {rows.map((row) => (
              <div key={row.key} className="track-import-row">
                <Checkbox
                  checked={row.checked}
                  onChange={(event) =>
                    setRows((current) =>
                      current.map((item) =>
                        item.key === row.key ? { ...item, checked: event.target.checked } : item,
                      ),
                    )
                  }
                />
                <div className="track-import-fields">
                  <Space size={6} wrap>
                    <Typography.Text strong>{row.preview.record.company}</Typography.Text>
                    <Typography.Text type="secondary">{row.preview.record.title}</Typography.Text>
                    <Tag color={MERGE_ACTION_COLORS[row.preview.action]}>
                      {MERGE_ACTION_LABELS[row.preview.action]}
                    </Tag>
                    <Tag>{TRACK_STATUS_LABELS[row.preview.record.status]}</Tag>
                  </Space>
                  {/* 原因比结论更重要：用户据此判断这条该不该勾。 */}
                  <Typography.Text type="secondary" className="track-import-reason">
                    {row.preview.reason}
                  </Typography.Text>
                  {row.preview.record.evidence && (
                    <Typography.Text type="secondary" className="track-import-evidence">
                      依据：{row.preview.record.evidence}
                    </Typography.Text>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Space>
    </Modal>
  );
}
