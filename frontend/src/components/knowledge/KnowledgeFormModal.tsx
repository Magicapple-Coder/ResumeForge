/** 知识库条目编辑：标题、分类、标签、来源与 Markdown 正文。 */

import { App, Button, Form, Input, Modal, Select, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import type { Knowledge, KnowledgePayload } from "../../types";
import { KNOWLEDGE_CATEGORIES } from "../../types";

interface Props {
  open: boolean;
  /** 传入条目表示编辑，传 null 表示新建。 */
  entry: Knowledge | null;
  categories: string[];
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (payload: KnowledgePayload) => void;
}

export default function KnowledgeFormModal({
  open,
  entry,
  categories,
  submitting,
  onCancel,
  onSubmit,
}: Props) {
  const { message } = App.useApp();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<string>("其他");
  const [tags, setTags] = useState<string[]>([]);
  const [source, setSource] = useState("手动录入");
  const [content, setContent] = useState("");

  useEffect(() => {
    if (!open) return;
    setTitle(entry?.title ?? "");
    setCategory(entry?.category || "其他");
    setTags(entry?.tags ?? []);
    setSource(entry?.source || "手动录入");
    setContent(entry?.content ?? "");
  }, [entry, open]);

  const options = Array.from(new Set([...categories, ...KNOWLEDGE_CATEGORIES]));

  const submit = () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      message.warning("请填写标题");
      return;
    }
    onSubmit({
      title: trimmedTitle,
      category: category.trim() || "其他",
      tags: tags.map((tag) => tag.trim()).filter(Boolean),
      source: source.trim() || "手动录入",
      content,
    });
  };

  return (
    <Modal
      title={entry ? `编辑条目：${entry.title}` : "新增一条知识"}
      open={open}
      width={760}
      onCancel={onCancel}
      maskClosable={!submitting}
      footer={
        <Space>
          <Button onClick={onCancel} disabled={submitting}>
            取消
          </Button>
          <Button type="primary" loading={submitting} onClick={submit}>
            保存
          </Button>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        知识库用来沉淀愿意反复查阅的成文内容：面经总结、简历技巧、求职策略、行业笔记等。 正文支持
        Markdown，保存后会按标题、列表、表格等结构渲染。
      </Typography.Paragraph>
      <Form layout="vertical">
        <Form.Item label="标题" required>
          <Input
            value={title}
            maxLength={200}
            placeholder="如：STAR 法则 / 自我介绍模板"
            onChange={(event) => setTitle(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="分类">
          <Select
            // tags 模式的取值是数组，这里始终只放一项，对外仍当单个字符串用。
            value={category ? [category] : []}
            showSearch
            options={options.map((item) => ({ value: item, label: item }))}
            mode="tags"
            maxCount={1}
            onChange={(values: string[]) => setCategory(values[values.length - 1] ?? "其他")}
            placeholder="选择或输入一个新分类"
          />
        </Form.Item>
        <Form.Item label="标签">
          <Select
            mode="tags"
            value={tags}
            maxCount={20}
            placeholder="输入标签后回车，如：简历、STAR、量化"
            onChange={setTags}
            tokenSeparators={[",", "，"]}
          />
        </Form.Item>
        <Form.Item label="来源">
          <Input
            value={source}
            maxLength={64}
            placeholder="如：手动录入 / 面经导入"
            onChange={(event) => setSource(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="正文内容" style={{ marginBottom: 0 }}>
          <Input.TextArea
            value={content}
            autoSize={{ minRows: 8, maxRows: 20 }}
            placeholder={"支持 Markdown：\n# 标题\n- 列表项\n**加粗**、`代码`、表格等"}
            onChange={(event) => setContent(event.target.value)}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
