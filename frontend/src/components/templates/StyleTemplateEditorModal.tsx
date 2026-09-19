/**
 * 样式模板编辑器：改 HTML/CSS，右侧实时看渲染效果。
 *
 * 两个刻意的设计：
 * 1. **从内置模板复制**是新建的默认入口：让用户从一份能用的模板开始改，比面对空白框强，
 *    也顺便保证了 `{% include "_resume_sections.j2" %}` 这类必要结构不会写漏。
 * 2. 预览走服务端渲染（`/api/resume-templates/preview`），所以看到的就是导出的效果；
 *    模板语法写错时错误信息直接显示在预览区，不会等到保存后才发现。
 */
import { Alert, App, Button, Form, Input, Modal, Space, Spin, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { previewResumeTemplate } from "../../api/resumes";
import {
  createResumeTemplate,
  fetchResumeTemplate,
  updateResumeTemplate,
} from "../../api/resumeTemplates";
import type { ResumeFontScale } from "../../types";
import A4PreviewFrame from "./A4PreviewFrame";

interface Props {
  open: boolean;
  /** 传入 id 表示编辑已有模板；否则新建。 */
  templateId?: number | null;
  /** 新建时的初始 HTML（通常是从某个内置模板复制的副本）。 */
  initialHtml?: string;
  initialName?: string;
  fontScale?: ResumeFontScale;
  onClose: () => void;
  onSaved: () => void;
}

const STARTER_HINT =
  "模板是一份完整的 HTML 页面，可用的变量：{{ resume.* }}（简历内容）、{{ page_limit }}（页数）、" +
  '{{ base_px }}（基准字号像素）、{{ csp_nonce }}。正文结构可以直接 include：{% include "_resume_sections.j2" %}';

export default function StyleTemplateEditorModal({
  open,
  templateId,
  initialHtml = "",
  initialName = "",
  fontScale = "standard",
  onClose,
  onSaved,
}: Props) {
  const { message } = App.useApp();
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState("");
  const [html, setHtml] = useState(initialHtml);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(initialName);
    setHtml(initialHtml);
    setDescription("");
    setPreview("");
    setPreviewError("");
    if (!templateId) return;
    setLoading(true);
    fetchResumeTemplate(templateId)
      .then((detail) => {
        setName(detail.name);
        setDescription(detail.description);
        setHtml(detail.html);
      })
      .catch((error) => message.error(error instanceof Error ? error.message : "读取模板失败"))
      .finally(() => setLoading(false));
  }, [open, templateId, initialName, initialHtml, message]);

  const runPreview = useCallback(
    async (source: string) => {
      if (!source.trim()) return;
      setPreviewing(true);
      setPreviewError("");
      try {
        setPreview(await previewResumeTemplate({ html: source, font_scale: fontScale }));
      } catch (error) {
        setPreview("");
        setPreviewError(error instanceof Error ? error.message : "预览渲染失败");
      } finally {
        setPreviewing(false);
      }
    },
    [fontScale],
  );

  // 首次打开就渲染一次，用户不用先点"预览"才知道长什么样。
  useEffect(() => {
    if (open && html.trim()) void runPreview(html);
  }, [open, html, runPreview]);

  const save = async () => {
    if (!name.trim()) {
      message.warning("请填写模板名称");
      return;
    }
    if (html.trim().length < 40) {
      message.warning("模板内容太短，请提供完整的 HTML");
      return;
    }
    setSaving(true);
    try {
      if (templateId) {
        await updateResumeTemplate(templateId, { name, description, html });
        message.success("模板已更新");
      } else {
        await createResumeTemplate({ name, description, html, kind: "style" });
        message.success("模板已创建，可以在生成简历时选用");
      }
      onSaved();
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={templateId ? "编辑样式模板" : "自制样式模板"}
      open={open}
      onCancel={onClose}
      onOk={() => void save()}
      okText="保存模板"
      confirmLoading={saving}
      width="min(1120px, 96vw)"
      styles={{
        body: { maxHeight: "calc(100vh - 220px)", overflowY: "auto", overflowX: "hidden" },
      }}
      destroyOnHidden
    >
      {loading ? (
        <Spin />
      ) : (
        <div className="style-template-editor">
          <Form layout="vertical" className="style-template-form">
            <Form.Item label="模板名称" required>
              <Input
                value={name}
                maxLength={40}
                placeholder="如：我的深蓝模板"
                onChange={(event) => setName(event.target.value)}
              />
            </Form.Item>
            <Form.Item label="说明（选填）">
              <Input
                value={description}
                maxLength={255}
                placeholder="一句话说明它适合什么场景"
                onChange={(event) => setDescription(event.target.value)}
              />
            </Form.Item>
            <Alert type="info" showIcon message={STARTER_HINT} style={{ marginBottom: 12 }} />
            <Form.Item label="模板 HTML">
              <Input.TextArea
                value={html}
                onChange={(event) => setHtml(event.target.value)}
                autoSize={{ minRows: 18, maxRows: 26 }}
                spellCheck={false}
                className="style-template-code"
              />
            </Form.Item>
            <Space wrap>
              <Button loading={previewing} onClick={() => void runPreview(html)}>
                刷新预览
              </Button>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                预览用的是内置示例简历；导入时脚本与外链会被自动去掉。
              </Typography.Text>
            </Space>
          </Form>
          <div className="style-template-preview">
            {previewError ? (
              <Alert type="error" showIcon message="模板渲染失败" description={previewError} />
            ) : previewing ? (
              <div className="style-template-preview-loading">
                <Spin />
              </div>
            ) : preview ? (
              <A4PreviewFrame html={preview} title="模板预览" maxHeight="66vh" />
            ) : (
              <Typography.Text type="secondary">还没有预览，点「刷新预览」试试。</Typography.Text>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
