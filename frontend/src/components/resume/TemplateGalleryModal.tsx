/**
 * 简历样式模板一览：每个模板都渲染一份真实预览，点一下就直接选用。
 *
 * 之前只有"经典"一种模板，选模板这件事无从比较；现在内置 6 种 + 用户自制模板，
 * 光看名字（"优雅""技术"）猜不出效果，所以这里用真的渲染结果说话——预览用的是
 * 用户自己的简历（没有简历时用内置示例内容）。
 */
import { App, Button, Empty, Modal, Segmented, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchResumeTemplates, previewResumeTemplate } from "../../api/resumes";
import type { ResumeFontScale, ResumeLayout, ResumeTemplateOption } from "../../types";

interface Props {
  open: boolean;
  layout: ResumeLayout;
  /** 用哪份简历做预览；为空时后端用内置示例内容。 */
  resumeId?: number;
  onSelect: (template: string) => void;
  onClose: () => void;
}

const FONT_SCALES: { value: ResumeFontScale; label: string }[] = [
  { value: "small", label: "小字号" },
  { value: "standard", label: "标准" },
  { value: "large", label: "大字号" },
];

export default function TemplateGalleryModal({ open, layout, resumeId, onSelect, onClose }: Props) {
  const { message } = App.useApp();
  const [templates, setTemplates] = useState<ResumeTemplateOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [failed, setFailed] = useState<Record<string, string>>({});
  const [previewScale, setPreviewScale] = useState<ResumeFontScale>(layout.font_scale);

  const loadTemplates = useCallback(async () => {
    try {
      const catalog = await fetchResumeTemplates();
      setTemplates(catalog.templates);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取模板清单失败");
    }
  }, [message]);

  useEffect(() => {
    if (open) void loadTemplates();
  }, [open, loadTemplates]);

  // 预览跟着"字号 + 格式模板"走：换字号或换版式后，缩略图应该一起变，
  // 否则用户按缩略图选出来的效果和实际生成的不一致。
  useEffect(() => {
    if (!open || templates.length === 0) return;
    let cancelled = false;
    setLoading(true);
    setPreviews({});
    setFailed({});
    void (async () => {
      const next: Record<string, string> = {};
      const errors: Record<string, string> = {};
      await Promise.all(
        templates.map(async (item) => {
          try {
            next[item.name] = await previewResumeTemplate({
              template_name: item.name,
              format_name: layout.format_name,
              page_limit: 1,
              font_scale: previewScale,
              resume_id: resumeId,
            });
          } catch (error) {
            errors[item.name] = error instanceof Error ? error.message : "预览渲染失败";
          }
        }),
      );
      if (cancelled) return;
      setPreviews(next);
      setFailed(errors);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, templates, layout.format_name, previewScale, resumeId]);

  const selectedName = layout.template;
  const body = useMemo(
    () => (
      <div className="template-gallery">
        <div className="template-gallery-toolbar">
          <Typography.Text type="secondary">
            预览用的是{resumeId ? "你选中的这份简历" : "内置示例内容"}，可以换字号看效果。
          </Typography.Text>
          <Segmented
            size="small"
            value={previewScale}
            options={FONT_SCALES}
            onChange={(value) => setPreviewScale(value as ResumeFontScale)}
          />
        </div>
        <div className="template-gallery-grid">
          {templates.map((item) => (
            <div
              key={item.name}
              className={`template-gallery-card${item.name === selectedName ? " is-active" : ""}`}
            >
              <div className="template-gallery-preview">
                {previews[item.name] ? (
                  <iframe
                    title={`${item.label} 预览`}
                    className="template-gallery-frame"
                    sandbox=""
                    srcDoc={previews[item.name]}
                  />
                ) : failed[item.name] ? (
                  <div className="template-gallery-error">{failed[item.name]}</div>
                ) : (
                  <div className="template-gallery-loading">
                    <Spin size="small" />
                  </div>
                )}
              </div>
              <div className="template-gallery-meta">
                <div className="template-gallery-title">
                  <span>{item.label}</span>
                  {item.custom ? <Tag color="blue">自制</Tag> : null}
                  {item.name === selectedName ? <Tag color="green">使用中</Tag> : null}
                </div>
                <Typography.Text type="secondary" className="template-gallery-desc">
                  {item.description || "用户自制的样式模板"}
                </Typography.Text>
                <Button
                  size="small"
                  type={item.name === selectedName ? "default" : "primary"}
                  disabled={item.name === selectedName}
                  onClick={() => onSelect(item.name)}
                >
                  {item.name === selectedName ? "当前使用" : "用这个模板"}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    ),
    [templates, previews, failed, selectedName, resumeId, previewScale, onSelect],
  );

  return (
    <Modal
      title="选择简历样式模板"
      open={open}
      onCancel={onClose}
      footer={null}
      width="min(1080px, 96vw)"
      styles={{ body: { maxHeight: "calc(100vh - 220px)", overflowY: "auto" } }}
      destroyOnHidden
    >
      {templates.length === 0 && !loading ? <Empty description="还没有可选模板" /> : body}
    </Modal>
  );
}
