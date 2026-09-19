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
  // 用户当前真实设定的格式覆盖（含 `font_scale_adjust` 字号系数）。缩略图必须带上它，
  // 否则"用户把字号拖到 14.3px、缩略图却仍是 14px"，选出来才发现不一样。
  const formatConfig = layout.format_config;
  // `format_config` 每次父渲染都是新对象引用，直接放进依赖会让预览随父组件任意重渲染
  // 而反复请求；用序列化签名判断"内容真的变了"。对象本身在闭包里读取。
  const formatConfigKey = JSON.stringify(formatConfig ?? {});

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

  // 预览跟着"字号 + 格式覆盖"走：换档位、换版式、或在外面拖过字号系数后，缩略图
  // 都要一起变，否则用户按缩略图选出来的效果和实际生成的不一致。
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
              // 把当前格式覆盖（含字号系数）一并传出：后端把 format_name 的基础版式
              // 与这份 format_config 叠加后再渲染，缩略图因此与用户实际生成的简历同口径。
              format_config: formatConfig,
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
    // format_config 用序列化签名 formatConfigKey 做依赖，避免对象引用每次渲染都变。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, templates, layout.format_name, formatConfigKey, previewScale, resumeId]);

  const selectedName = layout.template;
  const body = useMemo(
    () => (
      <div className="template-gallery">
        <div className="template-gallery-toolbar">
          <Typography.Text type="secondary">
            预览用的是{resumeId ? "你选中的这份简历" : "内置示例内容"}
            ，已带上你当前的版式与字号系数；上面的档位只作对比用。
          </Typography.Text>
          {/* 这个档位 Segmented 是**只读对比**入口：它不写回 layout.font_scale，也不自带
              系数，只决定缩略图用哪个基准档渲染。用户真实设定的字号系数
              （format_config.font_scale_adjust）由外面的滑块独占——两条路径不会各存一份
              字号，避免出现第二个"字号口径"。默认档位就是用户当前档位，所以缩略图默认
              显示的就是用户真实字号；换档位只是拿同一份系数去看另一个基准档。 */}
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
      styles={{
        body: { maxHeight: "calc(100vh - 220px)", overflowY: "auto", overflowX: "hidden" },
      }}
      destroyOnHidden
    >
      {templates.length === 0 && !loading ? <Empty description="还没有可选模板" /> : body}
    </Modal>
  );
}
