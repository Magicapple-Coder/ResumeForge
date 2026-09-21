/** 知识库：集中沉淀面经总结、简历技巧、求职策略、行业笔记等成文内容。 */
import { DeleteOutlined, EditOutlined, FileTextOutlined, PlusOutlined } from "@ant-design/icons";
import { App, Button, Card, Empty, Input, Modal, Select, Space, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createKnowledge,
  deleteKnowledge,
  listKnowledge,
  listKnowledgeCategories,
  updateKnowledge,
} from "../api/knowledge";
import { RowActions, RowContextMenu } from "../components/common/RowActions";
import { DetailTrigger } from "../components/common/RecordDetail";
import KnowledgeFormModal from "../components/knowledge/KnowledgeFormModal";
import { AssistantMessageContent } from "../features/assistant/components/AssistantMessageContent";
import type { Knowledge, KnowledgePayload } from "../types";
import { formatDateTime } from "../utils/format";

export default function KnowledgePage() {
  const { message } = App.useApp();
  const [entries, setEntries] = useState<Knowledge[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState<string>("");
  const [tag, setTag] = useState<string>("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Knowledge | null>(null);
  const [viewing, setViewing] = useState<Knowledge | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [items, categoryList] = await Promise.all([
        listKnowledge({ q: keyword, category }),
        listKnowledgeCategories(),
      ]);
      setEntries(items);
      setCategories(categoryList);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载知识库失败");
    } finally {
      setLoading(false);
    }
  }, [category, keyword, message]);

  useEffect(() => {
    void load();
  }, [load]);

  const categoryOptions = useMemo(
    () => [
      { value: "", label: "全部分类" },
      ...categories.map((item) => ({ value: item, label: item })),
    ],
    [categories],
  );

  // 标签筛选在本地做：后端列表已按 q/分类过滤，标签是同一结果集内的再筛选。
  const tagOptions = useMemo(() => {
    const all = Array.from(new Set(entries.flatMap((entry) => entry.tags))).sort();
    return [{ value: "", label: "全部标签" }, ...all.map((item) => ({ value: item, label: item }))];
  }, [entries]);

  const visibleEntries = useMemo(
    () => (tag ? entries.filter((entry) => entry.tags.includes(tag)) : entries),
    [entries, tag],
  );

  const submit = async (payload: KnowledgePayload) => {
    setSubmitting(true);
    try {
      if (editing) {
        await updateKnowledge(editing.id, payload);
        message.success("条目已更新");
      } else {
        await createKnowledge(payload);
        message.success("已加入知识库");
      }
      setFormOpen(false);
      setEditing(null);
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (entry: Knowledge) => {
    try {
      await deleteKnowledge(entry.id);
      message.success("已移入回收站，可在「回收站」里恢复");
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (entry: Knowledge) => {
    setEditing(entry);
    setFormOpen(true);
  };

  const actionsFor = (entry: Knowledge) => {
    const primary = [
      {
        key: "view",
        label: "查看",
        icon: <FileTextOutlined />,
        onClick: () => setViewing(entry),
      },
    ];
    const more = [
      { key: "edit", label: "编辑", icon: <EditOutlined />, onClick: () => openEdit(entry) },
      {
        key: "delete",
        label: "删除",
        danger: true,
        icon: <DeleteOutlined />,
        confirm: `删除条目「${entry.title}」？`,
        onClick: () => void remove(entry),
      },
    ];
    return { primary, more, all: [...primary, ...more] };
  };

  return (
    <div className="knowledge-page">
      <div className="knowledge-page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            知识库
          </Typography.Title>
          <Typography.Text type="secondary">
            沉淀面经总结、简历技巧、求职策略、行业笔记等成文内容。正文支持 Markdown，
            保存后按标题、列表、表格等结构渲染。
          </Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新增知识
        </Button>
      </div>

      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          allowClear
          placeholder="搜索标题或正文"
          style={{ width: 260 }}
          onSearch={setKeyword}
        />
        <Select
          aria-label="分类筛选"
          value={category}
          options={categoryOptions}
          style={{ width: 160 }}
          onChange={setCategory}
        />
        <Select
          aria-label="标签筛选"
          value={tag}
          options={tagOptions}
          style={{ width: 160 }}
          onChange={setTag}
        />
      </Space>

      {loading ? (
        <Spin />
      ) : visibleEntries.length === 0 ? (
        <Empty
          description={
            entries.length === 0
              ? "知识库还是空的，点右上角「新增知识」开始"
              : "没有符合筛选条件的条目"
          }
        />
      ) : (
        <div className="knowledge-grid">
          {visibleEntries.map((entry) => {
            const { primary, more, all } = actionsFor(entry);
            return (
              <RowContextMenu key={entry.id} items={all}>
                <DetailTrigger
                  label={`打开知识条目「${entry.title}」的详情`}
                  onOpen={() => setViewing(entry)}
                >
                  <Card size="small" className="knowledge-card">
                    <div className="knowledge-card-head">
                      <Tag color="blue">{entry.category}</Tag>
                      <RowActions primary={primary} more={more} />
                    </div>
                    <Typography.Title level={5} ellipsis={{ tooltip: entry.title }}>
                      {entry.title}
                    </Typography.Title>
                    {entry.tags.length > 0 && (
                      <Space size={4} wrap className="knowledge-card-tags">
                        {entry.tags.map((tag) => (
                          <Tag key={tag}>{tag}</Tag>
                        ))}
                      </Space>
                    )}
                    {entry.content && (
                      <Typography.Paragraph
                        type="secondary"
                        ellipsis={{ rows: 3 }}
                        className="knowledge-card-content"
                      >
                        {entry.content}
                      </Typography.Paragraph>
                    )}
                    <div className="knowledge-card-meta">
                      {entry.source && (
                        <Typography.Text type="secondary">{entry.source}</Typography.Text>
                      )}
                      <Typography.Text type="secondary">
                        {formatDateTime(entry.updated_at)}
                      </Typography.Text>
                    </div>
                  </Card>
                </DetailTrigger>
              </RowContextMenu>
            );
          })}
        </div>
      )}

      <KnowledgeFormModal
        open={formOpen}
        entry={editing}
        categories={categories}
        submitting={submitting}
        onCancel={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSubmit={(payload) => void submit(payload)}
      />

      <Modal
        open={viewing !== null}
        title={viewing?.title}
        width={760}
        footer={null}
        onCancel={() => setViewing(null)}
      >
        {viewing && (
          <>
            <Space wrap style={{ marginBottom: 12 }}>
              <Tag color="blue">{viewing.category}</Tag>
              {viewing.tags.map((tag) => (
                <Tag key={tag}>{tag}</Tag>
              ))}
              {viewing.source && (
                <Typography.Text type="secondary">{viewing.source}</Typography.Text>
              )}
            </Space>
            <div className="knowledge-card-content">
              <AssistantMessageContent content={viewing.content} />
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
