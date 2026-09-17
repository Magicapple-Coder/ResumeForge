/**
 * 格式模板编辑器：调行高、页边距、强调色这类版式参数。
 *
 * 与样式模板分开是有意的：用户想"压到一页"时不该去改 CSS。这里每个参数都有范围，
 * 越界值后端会直接丢弃，所以界面上也用 InputNumber 限死，不让用户白改一次。
 */
import { App, Button, Form, Input, InputNumber, Modal, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { createResumeTemplate, updateResumeTemplate } from "../../api/resumeTemplates";
import type { ResumeFormatField, ResumeTemplateDetail } from "../../types";

interface Props {
  open: boolean;
  /** 可调参数清单与内置预设由 /api/resumes/templates 下发。 */
  fields: ResumeFormatField[];
  template?: ResumeTemplateDetail | null;
  onClose: () => void;
  onSaved: () => void;
}

type ConfigValue = string | number | null;

export default function FormatTemplateEditorModal({
  open,
  fields,
  template,
  onClose,
  onSaved,
}: Props) {
  const { message } = App.useApp();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [values, setValues] = useState<Record<string, ConfigValue>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(template?.name ?? "");
    setDescription(template?.description ?? "");
    setValues({ ...(template?.config ?? {}) });
  }, [open, template]);

  const setValue = (key: string, value: ConfigValue) =>
    setValues((current) => ({ ...current, [key]: value }));

  const save = async () => {
    if (!name.trim()) {
      message.warning("请填写模板名称");
      return;
    }
    // 只提交填过的项：空值代表"沿用样式模板自带的设置"。
    const config: Record<string, string | number> = {};
    Object.entries(values).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== "") config[key] = value;
    });
    if (Object.keys(config).length === 0) {
      message.warning("至少设置一项参数，否则这个格式模板没有任何效果");
      return;
    }
    setSaving(true);
    try {
      if (template) {
        await updateResumeTemplate(template.id, { name, description, config });
        message.success("版式已更新");
      } else {
        await createResumeTemplate({ name, description, config, kind: "format" });
        message.success("版式已创建，可以在生成或预览简历时选用");
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
      title={template ? "编辑格式模板" : "自制格式模板"}
      open={open}
      onCancel={onClose}
      onOk={() => void save()}
      okText="保存版式"
      confirmLoading={saving}
      width={620}
      destroyOnHidden
    >
      <Form layout="vertical">
        <Form.Item label="名称" required>
          <Input
            value={name}
            maxLength={40}
            placeholder="如：我的紧凑版式"
            onChange={(event) => setName(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="说明（选填）">
          <Input
            value={description}
            maxLength={255}
            placeholder="一句话说明它解决什么问题"
            onChange={(event) => setDescription(event.target.value)}
          />
        </Form.Item>
        {fields.map((field) => (
          <Form.Item
            key={field.key}
            label={field.label}
            extra={field.description}
            style={{ marginBottom: 12 }}
          >
            {field.type === "color" ? (
              <Space>
                <input
                  type="color"
                  aria-label={field.label}
                  value={
                    typeof values[field.key] === "string" ? String(values[field.key]) : "#16365c"
                  }
                  onChange={(event) => setValue(field.key, event.target.value)}
                  className="format-color-input"
                />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {typeof values[field.key] === "string" ? String(values[field.key]) : "未设置"}
                </Typography.Text>
                {values[field.key] ? (
                  <Button size="small" type="link" onClick={() => setValue(field.key, null)}>
                    清除
                  </Button>
                ) : null}
              </Space>
            ) : (
              <InputNumber
                value={typeof values[field.key] === "number" ? (values[field.key] as number) : null}
                min={field.min}
                max={field.max}
                step={field.step ?? 0.1}
                placeholder="未设置"
                onChange={(value) => setValue(field.key, value ?? null)}
              />
            )}
          </Form.Item>
        ))}
      </Form>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        留空表示沿用样式模板自带的设置；只有填过的项才会生效。
      </Typography.Text>
    </Modal>
  );
}
