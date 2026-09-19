/** 单个模板的放大预览：可切字号与版式，看的始终是真实渲染结果。 */
import { Alert, Modal, Segmented, Space, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { previewResumeTemplate } from "../../api/resumes";
import type { ResumeFontScale, ResumeFormatPreset, ResumeTemplateDetail } from "../../types";
import A4PreviewFrame from "./A4PreviewFrame";

interface Props {
  template: ResumeTemplateDetail | null;
  formatPresets: ResumeFormatPreset[];
  onClose: () => void;
}

const FONT_SCALES: { value: ResumeFontScale; label: string }[] = [
  { value: "small", label: "小字号" },
  { value: "standard", label: "标准" },
  { value: "large", label: "大字号" },
];

export default function TemplatePreviewModal({ template, formatPresets, onClose }: Props) {
  const [fontScale, setFontScale] = useState<ResumeFontScale>("standard");
  const [formatName, setFormatName] = useState("");
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!template) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    void previewResumeTemplate({
      template_id: template.kind === "style" ? template.id : undefined,
      template_name: template.kind === "format" ? "classic" : undefined,
      format_name: template.kind === "format" ? template.name : formatName,
      font_scale: fontScale,
    })
      .then((rendered) => {
        if (!cancelled) setHtml(rendered);
      })
      .catch((err) => {
        if (!cancelled) {
          setHtml("");
          setError(err instanceof Error ? err.message : "预览失败");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [template, fontScale, formatName]);

  return (
    <Modal
      title={template ? `模板预览 · ${template.name}` : "模板预览"}
      open={!!template}
      onCancel={onClose}
      footer={null}
      width="min(1000px, 96vw)"
      styles={{
        body: { maxHeight: "calc(100vh - 200px)", overflowY: "auto", overflowX: "hidden" },
      }}
      destroyOnHidden
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented
          size="small"
          value={fontScale}
          options={FONT_SCALES}
          onChange={(value) => setFontScale(value as ResumeFontScale)}
        />
        {template?.kind === "style" ? (
          <Segmented
            size="small"
            value={formatName || ""}
            options={[
              { value: "", label: "模板自带版式" },
              ...formatPresets.map((item) => ({ value: item.name, label: item.label })),
            ]}
            onChange={(value) => setFormatName(String(value))}
          />
        ) : null}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          预览使用内置示例简历内容
        </Typography.Text>
      </Space>
      {error ? (
        <Alert type="error" showIcon message="预览渲染失败" description={error} />
      ) : loading ? (
        <div className="template-preview-loading">
          <Spin />
        </div>
      ) : (
        <A4PreviewFrame html={html} title="模板预览" />
      )}
    </Modal>
  );
}
