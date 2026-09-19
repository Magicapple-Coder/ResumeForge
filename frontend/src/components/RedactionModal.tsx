/** 一键脱敏：预览脱敏后的简历 + 下载脱敏版（独立文件，不回写）。 */
import { App, Button, Checkbox, Descriptions, Modal, Space, Spin, Typography } from "antd";
import { useState } from "react";
import { exportResumeWithOptions, redactResume } from "../api/resumes";
import type { ResumeContent } from "../types";
import {
  DEFAULT_REDACTION_OPTIONS,
  REDACTION_FIELDS,
  type RedactionOptions,
} from "../types/export";
import { downloadBlob } from "../utils/download";

interface Props {
  recordId: number;
  open: boolean;
  onClose: () => void;
}

export default function RedactionModal({ recordId, open, onClose }: Props) {
  const { message } = App.useApp();
  const [options, setOptions] = useState<RedactionOptions>(DEFAULT_REDACTION_OPTIONS);
  const [preview, setPreview] = useState<ResumeContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  const previewRedacted = async () => {
    setLoading(true);
    try {
      setPreview(await redactResume(recordId, options));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "脱敏预览失败");
    } finally {
      setLoading(false);
    }
  };

  const downloadRedacted = async () => {
    setExporting(true);
    try {
      const result = await exportResumeWithOptions(recordId, {
        format: "pdf",
        redact: true,
        redact_options: options,
      });
      downloadBlob(result.blob, result.filename);
      message.success("脱敏版已开始下载");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "下载脱敏版失败");
    } finally {
      setExporting(false);
    }
  };

  const setField = (key: keyof RedactionOptions, checked: boolean) => {
    setOptions((prev) => ({ ...prev, [key]: checked }));
  };

  return (
    <Modal
      title="一键脱敏"
      open={open}
      onCancel={onClose}
      footer={null}
      width="min(560px, 92vw)"
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <div>
          <Typography.Text strong>遮罩范围</Typography.Text>
          <div style={{ marginTop: 8 }}>
            {REDACTION_FIELDS.map((field) => (
              <Checkbox
                key={field.key}
                checked={options[field.key]}
                onChange={(event) => setField(field.key, event.target.checked)}
              >
                {field.label}
              </Checkbox>
            ))}
          </div>
        </div>

        <Space>
          <Button type="primary" loading={loading} onClick={() => void previewRedacted()}>
            预览脱敏
          </Button>
          <Button loading={exporting} onClick={() => void downloadRedacted()}>
            下载脱敏版（PDF）
          </Button>
        </Space>

        {loading && <Spin />}
        {!loading && preview && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="姓名">{preview.name}</Descriptions.Item>
            <Descriptions.Item label="手机">{preview.phone}</Descriptions.Item>
            <Descriptions.Item label="邮箱">{preview.email}</Descriptions.Item>
            <Descriptions.Item label="最近公司">
              {preview.experience[0]?.company ?? "-"}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Space>
    </Modal>
  );
}
