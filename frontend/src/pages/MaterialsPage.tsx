/** 资料箱：集中管理找工作和面试相关的材料（证书、作品、面经、复盘、链接、笔记）。 */
import {
  DeleteOutlined,
  EditOutlined,
  LinkOutlined,
  PaperClipOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { App, Button, Card, Empty, Input, Select, Space, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createMaterial,
  deleteMaterial,
  listMaterialCategories,
  listMaterials,
  updateMaterial,
} from "../api/material";
import MaterialFormModal from "../components/materials/MaterialFormModal";
import { RowActions, RowContextMenu } from "../components/common/RowActions";
import type { Material, MaterialPayload } from "../types";
import { formatDateTime } from "../utils/format";

export default function MaterialsPage() {
  const { message } = App.useApp();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState<string>("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Material | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [items, categoryList] = await Promise.all([
        listMaterials({ keyword, category }),
        listMaterialCategories(),
      ]);
      setMaterials(items);
      setCategories(categoryList);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载资料失败");
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

  const submit = async (payload: MaterialPayload) => {
    setSubmitting(true);
    try {
      if (editing) {
        await updateMaterial(editing.id, payload);
        message.success("资料已更新");
      } else {
        await createMaterial(payload);
        message.success("已放进资料箱");
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

  const remove = async (material: Material) => {
    try {
      await deleteMaterial(material.id);
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

  const openEdit = (material: Material) => {
    setEditing(material);
    setFormOpen(true);
  };

  const actionsFor = (material: Material) => [
    { key: "edit", label: "编辑", icon: <EditOutlined />, onClick: () => openEdit(material) },
    {
      key: "delete",
      label: "删除",
      danger: true,
      icon: <DeleteOutlined />,
      confirm: `删除资料「${material.title || material.category}」？`,
      onClick: () => void remove(material),
    },
  ];

  return (
    <div className="materials-page">
      <div className="materials-page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            资料箱
          </Typography.Title>
          <Typography.Text type="secondary">
            这里放与找工作、面试相关的材料：证书、作品、面经、公司信息、面试复盘、实习材料、链接与笔记。
            助手可以读它们、帮你归类整理、总结某一条，或把某条内容整理进个人资料。
          </Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          放入资料
        </Button>
      </div>

      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          allowClear
          placeholder="搜索标题、正文或备注"
          style={{ width: 260 }}
          onSearch={setKeyword}
        />
        <Select
          value={category}
          options={categoryOptions}
          style={{ width: 160 }}
          onChange={setCategory}
        />
      </Space>

      {loading ? (
        <Spin />
      ) : materials.length === 0 ? (
        <Empty description="资料箱还是空的，点右上角「放入资料」开始" />
      ) : (
        <div className="materials-grid">
          {materials.map((material) => (
            <RowContextMenu key={material.id} items={actionsFor(material)}>
              <Card size="small" className="material-card">
                <div className="material-card-head">
                  <Tag color="blue">{material.category}</Tag>
                  <RowActions more={actionsFor(material)} />
                </div>
                <Typography.Title level={5} ellipsis={{ tooltip: material.title }}>
                  {material.title || "（未命名资料）"}
                </Typography.Title>
                {material.content && (
                  <Typography.Paragraph
                    type="secondary"
                    ellipsis={{ rows: 3 }}
                    className="material-card-content"
                  >
                    {material.content}
                  </Typography.Paragraph>
                )}
                <div className="material-card-meta">
                  {material.files.length > 0 && (
                    <Typography.Text type="secondary">
                      <PaperClipOutlined /> {material.files.length} 个附件
                    </Typography.Text>
                  )}
                  {material.url && (
                    <Typography.Link href={material.url} target="_blank" rel="noopener noreferrer">
                      <LinkOutlined /> 链接
                    </Typography.Link>
                  )}
                  <Typography.Text type="secondary">
                    {formatDateTime(material.updated_at)}
                  </Typography.Text>
                </div>
              </Card>
            </RowContextMenu>
          ))}
        </div>
      )}

      <MaterialFormModal
        open={formOpen}
        material={editing}
        categories={categories}
        submitting={submitting}
        onCancel={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSubmit={(payload) => void submit(payload)}
      />
    </div>
  );
}
