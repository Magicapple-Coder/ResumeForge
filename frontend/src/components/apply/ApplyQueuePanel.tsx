/**
 * 投递队列：调整顺序、逐条确认准入、编辑招呼语与简历，然后显式开始投递。
 *
 * 准入提示直接读后端返回的 `admission` / `requires_confirm`（不在这里重判一次）：
 * - `block`（真实缺口）显示为「不投」并说明原因；
 * - `needs_confirm`（证据不足 / 待确认）提示需要用户确认；
 * - 未分析的岗位以「未分析」呈现。
 */
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  EditOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import { useEffect, useMemo, useState } from "react";
import {
  createApplyTask,
  listQueue,
  previewGreeting,
  removeQueueItem,
  reorderQueue,
  updateQueueItem,
} from "../../api/apply";
import { listResumes } from "../../api/resumes";
import { useApi } from "../../hooks/useApi";
import {
  ADMISSION_META,
  QUEUE_STATUS_META,
  type ApplyQueueItem,
  type ApplyTask,
  type ResumeBrief,
} from "../../types";

interface Props {
  /** 有任务正在运行时为真：禁止重复开始。 */
  disabled: boolean;
  onStarted: (task: ApplyTask) => void;
  /** 队列内容变化（增删改）时通知页面刷新概览。 */
  onChanged?: () => void;
}

function AdmissionTag({ item }: { item: ApplyQueueItem }) {
  if (item.admission === null) {
    // 还没有明确准入结论（admission 为空）时，后端仍可能判定"需逐条确认"
    // （如匹配分析结论为空 → requires_confirm）。此时必须把这个准入要求展示出来，
    // 不能一律显示「未分析」而把"需逐条确认"吞掉。只有既无结论又无需确认时才显示「未分析」。
    return item.requires_confirm ? <Tag color="gold">需逐条确认</Tag> : <Tag>未分析</Tag>;
  }
  const meta = ADMISSION_META[item.admission];
  return (
    <Space size={4} wrap>
      <Tag color={meta.color}>{meta.label}</Tag>
      {item.requires_confirm && <Tag color="gold">需逐条确认</Tag>}
    </Space>
  );
}

/** 编辑某条队列条目的招呼语与简历；招呼语可先按岗位生成一版再改。 */
function QueueItemEditor({
  item,
  onClose,
  onSaved,
}: {
  item: ApplyQueueItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<{ greeting: string; resume_id?: number }>();
  const [resumes, setResumes] = useState<ResumeBrief[]>([]);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    form.setFieldsValue({ greeting: item.greeting, resume_id: item.resume_id ?? undefined });
  }, [form, item]);

  useEffect(() => {
    if (item.job_id == null) return;
    let cancel = false;
    void listResumes({ job_id: item.job_id, page_size: 100 })
      .then((page) => {
        if (!cancel) setResumes(page.items);
      })
      .catch(() => {
        if (!cancel) setResumes([]);
      });
    return () => {
      cancel = true;
    };
  }, [item.job_id]);

  const generateGreeting = async () => {
    if (item.job_id == null) return;
    setGenerating(true);
    try {
      const preview = await previewGreeting({ job_id: item.job_id, item_id: item.id });
      form.setFieldValue("greeting", preview.greeting);
      message.success(
        preview.source === "generated" ? "已按岗位生成招呼语" : "已填入默认招呼语（未配置模型）",
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : "生成招呼语失败");
    } finally {
      setGenerating(false);
    }
  };

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await updateQueueItem(item.id, {
        greeting: values.greeting ?? "",
        ...(values.resume_id ? { resume_id: values.resume_id } : {}),
      });
      message.success("队列条目已更新");
      onSaved();
      onClose();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "更新失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`编辑「${item.job_title || "该岗位"}」`}
      open
      onCancel={onClose}
      footer={null}
      width={560}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="resume_id"
          label="使用简历"
          extra="留空则运行时用该岗位最近一份岗位版简历。"
        >
          <Select
            allowClear
            placeholder="按默认规则解析"
            options={resumes.map((resume) => ({ value: resume.id, label: resume.title }))}
          />
        </Form.Item>
        <Form.Item name="greeting" label="招呼语">
          <Input.TextArea rows={3} maxLength={1000} showCount />
        </Form.Item>
      </Form>
      <Space>
        <Button onClick={() => void generateGreeting()} loading={generating}>
          按岗位生成招呼语
        </Button>
        <Button type="primary" loading={saving} onClick={() => void save()}>
          保存
        </Button>
        <Button onClick={onClose}>取消</Button>
      </Space>
    </Modal>
  );
}

export default function ApplyQueuePanel({ disabled, onStarted, onChanged }: Props) {
  const { message } = App.useApp();
  const [reloadKey, setReloadKey] = useState(0);
  const { data, loading, error, reload, setData } = useApi<ApplyQueueItem[]>(
    () => listQueue(),
    [reloadKey],
  );
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [editing, setEditing] = useState<ApplyQueueItem | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  const items = useMemo(() => data ?? [], [data]);

  const refresh = () => {
    setReloadKey((value) => value + 1);
    onChanged?.();
  };

  const move = async (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    const order = items.map((item) => item.id);
    [order[index], order[target]] = [order[target], order[index]];
    setBusy(true);
    try {
      const updated = await reorderQueue(order);
      setData(updated);
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "调整顺序失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item: ApplyQueueItem) => {
    setBusy(true);
    try {
      await removeQueueItem(item.id);
      setSelectedIds((current) => current.filter((id) => id !== item.id));
      message.success("已移出队列");
      refresh();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "移出队列失败");
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    const chosen = selectedIds.length > 0 ? [...selectedIds] : undefined;
    setBusy(true);
    try {
      const task = await createApplyTask(
        chosen ? { job_ids: chosen, use_queue: false } : { use_queue: true },
      );
      message.success(chosen ? `已开始投递选中的 ${chosen.length} 个岗位` : "已开始投递队列");
      setSelectedIds([]);
      onStarted(task);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "开始投递失败");
    } finally {
      setBusy(false);
    }
  };

  const columns: ColumnsType<ApplyQueueItem> = [
    {
      title: "岗位",
      dataIndex: "job_title",
      render: (title: string, item) => (
        <Space direction="vertical" size={0}>
          <Typography.Text>{title || "（岗位已删除）"}</Typography.Text>
          {item.company && <Typography.Text type="secondary">{item.company}</Typography.Text>}
        </Space>
      ),
    },
    {
      title: "准入",
      key: "admission",
      width: 180,
      render: (_, item) => <AdmissionTag item={item} />,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (value: ApplyQueueItem["status"]) => {
        const meta = QUEUE_STATUS_META[value];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "简历 / 招呼语",
      key: "assets",
      render: (_, item) => (
        <Space direction="vertical" size={0}>
          <Typography.Text type="secondary">
            {item.resume_title || "按默认规则解析"}
          </Typography.Text>
          <Typography.Text type="secondary" ellipsis={{ tooltip: item.greeting || "默认招呼语" }}>
            {item.greeting || "默认招呼语"}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 210,
      render: (_, item, index) => (
        <Space>
          <Tooltip title="上移">
            <Button
              size="small"
              aria-label={`上移 ${item.job_title}`}
              icon={<ArrowUpOutlined />}
              disabled={index === 0 || busy}
              onClick={() => void move(index, -1)}
            />
          </Tooltip>
          <Tooltip title="下移">
            <Button
              size="small"
              aria-label={`下移 ${item.job_title}`}
              icon={<ArrowDownOutlined />}
              disabled={index === items.length - 1 || busy}
              onClick={() => void move(index, 1)}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button
              size="small"
              icon={<EditOutlined />}
              aria-label={`编辑 ${item.job_title}`}
              onClick={() => setEditing(item)}
            />
          </Tooltip>
          <Popconfirm
            title="移出投递队列？"
            okText="移出"
            cancelText="取消"
            onConfirm={() => void remove(item)}
          >
            <Button
              size="small"
              danger
              aria-label={`移出 ${item.job_title}`}
              icon={<DeleteOutlined />}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const rowSelection: TableRowSelection<ApplyQueueItem> = {
    selectedRowKeys: selectedIds,
    onChange: (keys) => setSelectedIds(keys.map(Number)),
    getCheckboxProps: (item) => ({ disabled: item.status !== "pending" || busy }),
  };

  if (loading && !data) return <Skeleton active paragraph={{ rows: 5 }} />;

  return (
    <div className="apply-queue-panel">
      <div className="apply-queue-head">
        <Space wrap>
          <Typography.Text type="secondary">
            共 {items.length} 个岗位；勾选后只投选中的，不勾选则整队列按顺序投递。
          </Typography.Text>
          <Button icon={<ReloadOutlined />} onClick={() => void reload()}>
            刷新
          </Button>
        </Space>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={busy}
          disabled={disabled || items.length === 0}
          onClick={() => void start()}
        >
          开始投递
        </Button>
      </div>

      {items.length === 0 ? (
        <Empty description="队列还是空的：到「岗位广场」的岗位详情里点「加入投递台」" />
      ) : (
        <Table<ApplyQueueItem>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={items}
          pagination={false}
          rowSelection={rowSelection}
          scroll={{ x: "max-content" }}
        />
      )}

      {editing && (
        <QueueItemEditor
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            refresh();
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}
