/** 模板市场（R-19）：按求职场景展示推荐的样式+版式+字号组合，全离线映射既有模板。 */
import { App, Alert, Button, Card, Col, Empty, Modal, Row, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { fetchResumeTemplates, previewResumeTemplate } from "../../api/resumes";
import { useApi } from "../../hooks/useApi";
import type { ResumeFontScale, ResumeTemplateCatalog } from "../../types";
import type { TemplateMarketPreset } from "../../types/templateMarket";
import A4PreviewFrame from "./A4PreviewFrame";

function styleLabel(catalog: ResumeTemplateCatalog | undefined, name: string): string {
  return catalog?.templates.find((item) => item.name === name)?.label ?? name;
}

function formatLabel(catalog: ResumeTemplateCatalog | undefined, name: string): string {
  if (!name) return "模板自带版式";
  return catalog?.format_presets.find((item) => item.name === name)?.label ?? name;
}

function fontLabel(catalog: ResumeTemplateCatalog | undefined, name: string): string {
  return catalog?.font_scales.find((item) => item.name === name)?.label ?? name;
}

/** 单个预设的放大预览：用内置示例简历内容真实渲染，所见即所得。 */
function MarketPreviewModal({
  preset,
  onClose,
}: {
  preset: TemplateMarketPreset | null;
  onClose: () => void;
}) {
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!preset) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setHtml("");
    void previewResumeTemplate({
      template_name: preset.template,
      format_name: preset.format_name,
      format_config: preset.format_config,
      font_scale: preset.font_scale as ResumeFontScale,
      page_limit: preset.page_limit,
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
  }, [preset]);

  return (
    <Modal
      title={preset ? `模板市场 · ${preset.label}` : "模板预览"}
      open={!!preset}
      onCancel={onClose}
      footer={null}
      width="min(1000px, 96vw)"
      styles={{
        body: { maxHeight: "calc(100vh - 200px)", overflowY: "auto", overflowX: "hidden" },
      }}
      destroyOnHidden
    >
      {error ? (
        <Alert type="error" showIcon message="预览渲染失败" description={error} />
      ) : loading ? (
        <div style={{ textAlign: "center", padding: 40 }}>
          <Spin />
        </div>
      ) : (
        <A4PreviewFrame html={html} title={`模板市场 · ${preset?.label ?? ""}`} />
      )}
    </Modal>
  );
}

export default function TemplateMarketTab() {
  const { message } = App.useApp();
  const { data: catalog, loading, error } = useApi(fetchResumeTemplates, []);
  const [preview, setPreview] = useState<TemplateMarketPreset | null>(null);

  const usePreset = (preset: TemplateMarketPreset) => {
    message.success(
      `已选用「${preset.label}」模板组合：${styleLabel(catalog, preset.template)} 样式 + ` +
        `${formatLabel(catalog, preset.format_name)} 版式 + ${fontLabel(catalog, preset.font_scale)} 字号`,
    );
  };

  return (
    <Card size="small" className="settings-card" title="模板市场" style={{ marginBottom: 16 }}>
      <Typography.Paragraph type="secondary">
        按求职场景给出「样式 + 版式 + 字号」的组合建议。所有预设都映射到内置模板，全离线、无需联网。
      </Typography.Paragraph>
      {error && <Alert type="error" showIcon message="读取模板市场失败" description={error} />}
      <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
        需要自定义模板？在下方工作台点「导入 HTML」或「复制改一份」即可。
      </Typography.Paragraph>
      {loading ? (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      ) : (catalog?.market ?? []).length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无模板市场预设" />
      ) : (
        <Row gutter={[16, 16]}>
          {(catalog?.market ?? []).map((preset) => (
            <Col key={preset.name} xs={24} sm={12} lg={12}>
              <Card size="small" title={preset.label}>
                <Typography.Paragraph type="secondary" style={{ minHeight: 44 }}>
                  {preset.description}
                </Typography.Paragraph>
                <Space wrap size={4} style={{ marginBottom: 12 }}>
                  <Tag>样式：{styleLabel(catalog, preset.template)}</Tag>
                  <Tag>版式：{formatLabel(catalog, preset.format_name)}</Tag>
                  <Tag>字号：{fontLabel(catalog, preset.font_scale)}</Tag>
                </Space>
                <Space>
                  <Button onClick={() => setPreview(preset)}>预览</Button>
                  <Button type="primary" onClick={() => usePreset(preset)}>
                    使用此模板
                  </Button>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}
      <MarketPreviewModal preset={preview} onClose={() => setPreview(null)} />
    </Card>
  );
}
