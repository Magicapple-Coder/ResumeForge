/** 技能详情 / 编辑：提示词与知识文件都在这一个弹窗里查看和修改。 */

import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { Alert, App, Button, Form, Input, Modal, Space, Spin, Switch, Typography } from "antd";
import { useEffect, useState } from "react";
import { createSkill, getSkill, updateSkill } from "../../api/skill";
import type { AssistantSkillFileInput } from "../../types";

/** 新建技能时用的预填内容（来自工作台的模板）。 */
export interface SkillDraft {
  name?: string;
  description?: string;
  prompt?: string;
}

interface Props {
  open: boolean;
  /** 传 id 表示编辑已有技能，传 null 表示新建。 */
  skillId: number | null;
  draft?: SkillDraft | null;
  onClose: () => void;
  onSaved: (skillId: number) => void;
}

export default function SkillEditorModal({ open, skillId, draft, onClose, onSaved }: Props) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [prompt, setPrompt] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [files, setFiles] = useState<AssistantSkillFileInput[]>([]);
  const [filesTruncated, setFilesTruncated] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (skillId === null) {
      setName(draft?.name ?? "");
      setDescription(draft?.description ?? "");
      setPrompt(draft?.prompt ?? "");
      setEnabled(true);
      setFiles([]);
      setFilesTruncated(false);
      return;
    }
    setLoading(true);
    void getSkill(skillId)
      .then((detail) => {
        setName(detail.name);
        setDescription(detail.description);
        setPrompt(detail.prompt);
        setEnabled(detail.enabled);
        setFiles(detail.file_details.map((item) => ({ path: item.path, content: item.content })));
        setFilesTruncated(detail.files_truncated);
      })
      .catch((error) => message.error(error instanceof Error ? error.message : "加载技能失败"))
      .finally(() => setLoading(false));
  }, [draft, message, open, skillId]);

  const save = async () => {
    if (!name.trim()) {
      message.warning("请填写技能名称");
      return;
    }
    if (!prompt.trim()) {
      message.warning("请填写技能提示词，它决定这个技能让助手怎么做");
      return;
    }
    setSaving(true);
    try {
      const base = { name: name.trim(), description: description.trim(), prompt, enabled };
      if (skillId === null) {
        const created = await createSkill({ ...base, files });
        message.success(`已创建技能「${created.name}」`);
        onSaved(created.id);
      } else {
        // 知识文件正文没完全加载时不要提交 files：那会把没加载到的内容覆盖成空。
        const updated = await updateSkill(skillId, filesTruncated ? base : { ...base, files });
        message.success(`已保存技能「${updated.name}」`);
        onSaved(updated.id);
      }
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存技能失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={skillId === null ? "新建助手技能" : "技能详情与编辑"}
      open={open}
      width={760}
      maskClosable={!saving}
      onCancel={onClose}
      footer={
        <Space>
          <Button onClick={onClose} disabled={saving}>
            关闭
          </Button>
          <Button type="primary" loading={saving} onClick={() => void save()}>
            保存
          </Button>
        </Space>
      }
    >
      {loading ? (
        <Spin />
      ) : (
        <Form layout="vertical">
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="技能提示词会加进助手的系统提示，等于给它加一条长期要求；知识文件是助手按需查阅的参考资料。"
          />
          <Form.Item label="技能名称" required>
            <Input
              value={name}
              maxLength={64}
              placeholder="如：简历要点精炼"
              onChange={(event) => setName(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="适用场景（一句话说明什么时候用它）">
            <Input
              value={description}
              maxLength={255}
              placeholder="如：把经历描述压缩成 3 条以内的简历要点"
              onChange={(event) => setDescription(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="启用">
            <Switch checked={enabled} onChange={setEnabled} />
          </Form.Item>
          <Form.Item label="技能提示词" required>
            <Input.TextArea
              value={prompt}
              autoSize={{ minRows: 8, maxRows: 20 }}
              placeholder={
                "用「你要…」「不要…」这类明确要求描述你希望助手怎么做。\n例如：改写简历要点时，每条不超过 35 字，必须包含动作动词与可核对的成果。"
              }
              onChange={(event) => setPrompt(event.target.value)}
            />
          </Form.Item>
          <Form.Item
            label={
              <Space>
                <span>知识文件</span>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  助手需要时才会读取（如常见面试题、公司清单）
                </Typography.Text>
              </Space>
            }
          >
            {filesTruncated && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="这个技能的知识文件体积很大，本次没有加载全部内容；保存时不会改动知识文件（只更新提示词与开关）。"
              />
            )}
            <Space direction="vertical" style={{ width: "100%" }}>
              {files.map((file, index) => (
                <div key={`${file.path}-${index}`} className="skill-file-editor">
                  <Space style={{ width: "100%" }} align="start">
                    <Input
                      value={file.path}
                      maxLength={255}
                      placeholder="文件名，如 面试问题.md"
                      style={{ width: 240 }}
                      onChange={(event) =>
                        setFiles((current) =>
                          current.map((item, i) =>
                            i === index ? { ...item, path: event.target.value } : item,
                          ),
                        )
                      }
                    />
                    <Button
                      type="text"
                      danger
                      aria-label={`删除知识文件 ${file.path}`}
                      icon={<DeleteOutlined />}
                      onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                    />
                  </Space>
                  <Input.TextArea
                    value={file.content}
                    autoSize={{ minRows: 3, maxRows: 10 }}
                    placeholder="知识文件内容（纯文本或 Markdown）"
                    onChange={(event) =>
                      setFiles((current) =>
                        current.map((item, i) =>
                          i === index ? { ...item, content: event.target.value } : item,
                        ),
                      )
                    }
                  />
                </div>
              ))}
              <Button
                icon={<PlusOutlined />}
                onClick={() => setFiles((current) => [...current, { path: "", content: "" }])}
              >
                添加知识文件
              </Button>
            </Space>
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}
