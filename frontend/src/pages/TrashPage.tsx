/**
 * 回收站：六类被删除的内容集中在这里，可以恢复，也可以彻底删除。
 *
 * 为什么值得单独一个页面：在这之前**所有删除都是不可逆的**，用户不敢删；现在删除只打一个
 * 时间戳，东西先落到这里。页面上有两条不能含糊的边界，它们在交互上被刻意做成不一样重：
 *
 * - **恢复**是安全的 → 一键就行，不用确认；
 * - **彻底删除**不可逆 → 必须二次确认，而且确认文案要说清"删了就找不回来了"。
 *
 * 每条都标出**类型**与**删除时间**：用户来这儿找的往往是"我前几天删的那个岗位"，
 * 只有标题没有时间等于让他一条条点开看。
 */
import { DeleteOutlined, UndoOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Empty,
  Popconfirm,
  Segmented,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import { useState } from "react";
import {
  emptyTrash,
  getTrash,
  purgeTrashItem,
  purgeTrashItems,
  restoreTrashItem,
  restoreTrashItems,
} from "../api/trash";
import { useApi } from "../hooks/useApi";
import type { TrashBatchItem, TrashItem } from "../types";

const ALL = "__all__";

/** 把后端的 ISO 时间显示成"到分钟"的本地时间。 */
function deletedAtText(value: string | null): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 16);
}

export default function TrashPage() {
  const { message } = App.useApp();
  const [type, setType] = useState<string>(ALL);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const { data, loading, error, reload } = useApi(
    () => getTrash(type === ALL ? {} : { type }),
    [type],
  );

  const labels = data?.labels ?? {};
  const items = data?.items ?? [];
  const counts = data?.counts ?? {};

  const selectedItems = (): TrashBatchItem[] =>
    items
      .filter((item) => selectedKeys.includes(`${item.type}-${item.id}`))
      .map((item) => ({ type_key: item.type, id: item.id }));

  const batchRestore = async () => {
    const chosen = selectedItems();
    if (chosen.length === 0) return;
    try {
      const result = await restoreTrashItems(chosen);
      message.success(`已恢复 ${result.restored} 条`);
      setSelectedKeys([]);
      await reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "批量恢复失败");
    }
  };

  const batchPurge = async () => {
    const chosen = selectedItems();
    if (chosen.length === 0) return;
    try {
      const result = await purgeTrashItems(chosen);
      message.success(`已彻底删除 ${result.purged} 条`);
      setSelectedKeys([]);
      await reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "批量彻底删除失败");
    }
  };

  const options = [
    { label: `全部（${data?.total ?? 0}）`, value: ALL },
    // 只列出**当前有内容**的类型：回收站里的空类型只会让筛选器变长。
    ...Object.entries(labels)
      .filter(([key]) => (counts[key] ?? 0) > 0)
      .map(([key, label]) => ({ label: `${label}（${counts[key]}）`, value: key })),
  ];

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      message.success(success);
      await reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "操作失败");
    }
  };

  const columns: ColumnsType<TrashItem> = [
    {
      title: "类型",
      dataIndex: "type_label",
      width: 110,
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "名称",
      dataIndex: "title",
      render: (value: string, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{value || "（无标题）"}</Typography.Text>
          {row.subtitle && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {row.subtitle}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: "删除时间",
      dataIndex: "deleted_at",
      width: 160,
      render: (value: string | null) => deletedAtText(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 190,
      render: (_value, row) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<UndoOutlined />}
            aria-label={`恢复 ${row.title || row.type_label}`}
            onClick={() =>
              void run(() => restoreTrashItem(row.type, row.id), `已恢复「${row.title}」`)
            }
          >
            恢复
          </Button>
          <Popconfirm
            title="彻底删除？"
            // 确认文案要把后果说白：这是全应用唯一不可逆的动作。
            description={`「${row.title || row.type_label}」将被永久删除，无法恢复。`}
            okText="彻底删除"
            // 显式 aria-label：antd 会给两字中文按钮自动插空格（"取 消"），
            // 不写死名称则界面与测试都容易踩到这个坑（同 CollectResultPanel 的处理）。
            okButtonProps={{
              danger: true,
              "aria-label": `确认彻底删除 ${row.title || row.type_label}`,
            }}
            cancelText="取消"
            cancelButtonProps={{ "aria-label": `取消彻底删除 ${row.title || row.type_label}` }}
            onConfirm={() =>
              void run(() => purgeTrashItem(row.type, row.id), `已彻底删除「${row.title}」`)
            }
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              aria-label={`彻底删除 ${row.title || row.type_label}`}
            >
              彻底删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const rowSelection: TableRowSelection<TrashItem> = {
    selectedRowKeys: selectedKeys,
    onChange: (keys) => setSelectedKeys(keys.map(String)),
  };

  return (
    <div className="trash-page">
      <div className="trash-page-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            回收站
          </Typography.Title>
          <Typography.Text type="secondary">
            删除的内容会先到这里，不会直接消失；恢复是一键的。「彻底删除」才会真正抹掉， 不可撤销。
          </Typography.Text>
        </Space>
        {items.length > 0 && (
          <Popconfirm
            title={`清空${type === ALL ? "回收站" : "这一类"}？`}
            description={`将永久删除 ${
              type === ALL ? (data?.total ?? 0) : (counts[type] ?? 0)
            } 条内容，无法恢复。`}
            okText="清空"
            okButtonProps={{ danger: true, "aria-label": "确认清空回收站" }}
            cancelText="取消"
            cancelButtonProps={{ "aria-label": "取消清空回收站" }}
            onConfirm={() => void run(() => emptyTrash(type === ALL ? "" : type), "回收站已清空")}
          >
            <Button danger icon={<DeleteOutlined />}>
              清空{type === ALL ? "回收站" : "这一类"}
            </Button>
          </Popconfirm>
        )}
        {selectedKeys.length > 0 && (
          <Space>
            <Button icon={<UndoOutlined />} onClick={() => void batchRestore()}>
              批量恢复（{selectedKeys.length}）
            </Button>
            <Popconfirm
              title={`彻底删除选中的 ${selectedKeys.length} 条？`}
              description="将永久删除，无法恢复。"
              okText="彻底删除"
              okButtonProps={{ danger: true, "aria-label": "确认批量彻底删除" }}
              cancelText="取消"
              cancelButtonProps={{ "aria-label": "取消批量彻底删除" }}
              onConfirm={() => void batchPurge()}
            >
              <Button danger icon={<DeleteOutlined />}>
                批量彻底删除
              </Button>
            </Popconfirm>
          </Space>
        )}
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="回收站里的内容不会出现在其它页面"
        description="岗位、简历、投递记录、台账条目、资料箱材料与助手会话——删除后它们立刻从各自的列表、首页统计和搜索里消失，只在这里可见。"
      />

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

      {data && data.total > 0 && (
        <Segmented
          style={{ marginBottom: 12 }}
          value={type}
          onChange={(value) => setType(value as string)}
          options={options}
        />
      )}

      {loading && !data ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="回收站是空的。删除内容后，它们会出现在这里，可以随时恢复。"
        />
      ) : (
        <Table
          rowKey={(row) => `${row.type}-${row.id}`}
          size="middle"
          columns={columns}
          dataSource={items}
          pagination={false}
          rowSelection={rowSelection}
        />
      )}
    </div>
  );
}
