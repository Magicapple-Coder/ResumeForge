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
  EyeOutlined,
  MoreOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  App,
  Alert,
  Button,
  Dropdown,
  Empty,
  Form,
  Input,
  Menu,
  Modal,
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
import { formatDateTime } from "../../utils/format";
import { RecordDetailDrawer } from "../common/RecordDetail";
import { useRowActionMenu } from "../common/rowActionMenu";

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
  const [detail, setDetail] = useState<ApplyQueueItem | null>(null);
  const [busy, setBusy] = useState(false);
  // 右键菜单：记录鼠标位置与目标行，用定位式 Menu 渲染（避免把 <tr> 包进 Dropdown 造成行重建竞态）。
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    record: ApplyQueueItem;
  } | null>(null);
  const buildMenu = useRowActionMenu();

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  const items = useMemo(() => data ?? [], [data]);
  const pendingItems = useMemo(
    () => items.filter((item) => item.status === "pending" && item.job_id !== null),
    [items],
  );
  // 来源不支持的待投条目：它们**无法**被自动投递，整队列投递时会被后端一次性拦下。
  // 提前在页面上说明，用户才不会在点了「开始投递」之后才被一条 409 拦住。
  const unsupportedPending = useMemo(
    () => pendingItems.filter((item) => item.apply_supported === false),
    [pendingItems],
  );

  const refresh = () => {
    setReloadKey((value) => value + 1);
    onChanged?.();
  };

  /**
   * 右键菜单项：与「···」菜单一致（编辑 / 移出队列）。移出队列走 Modal.confirm。
   */
  /**
   * 行操作的唯一清单：右键菜单与「···」下拉都从这里取，避免两处慢慢长歪。
   * 「移出队列」走 Modal.confirm（由 buildMenu 统一加二次确认）。
   */
  const rowMenuItems = (record: ApplyQueueItem) =>
    buildMenu([
      {
        key: "detail",
        label: "查看详情",
        icon: <EyeOutlined />,
        onClick: () => setDetail(record),
      },
      {
        key: "edit",
        label: "编辑",
        icon: <EditOutlined />,
        onClick: () => setEditing(record),
      },
      {
        key: "remove",
        label: "移出队列",
        danger: true,
        icon: <DeleteOutlined />,
        confirm: "移出投递队列？",
        onClick: () => void remove(record),
      },
    ]);

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
    // Table 的 rowKey 是队列条目 id，而后端 /apply/tasks 的 job_ids 明确要求岗位 id。
    // 两种 id 通常不同，直接提交 selectedIds 会投错岗位，甚至在碰巧存在同号岗位时静默误投。
    const chosen =
      selectedIds.length > 0
        ? items
            .filter(
              (item): item is ApplyQueueItem & { job_id: number } =>
                selectedIds.includes(item.id) && item.status === "pending" && item.job_id !== null,
            )
            .map((item) => item.job_id)
        : undefined;
    if (selectedIds.length > 0 && chosen?.length === 0) {
      message.warning("选中的条目已经不可投递，请刷新队列后重试");
      return;
    }
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

  /**
   * 列宽全部写死、`tableLayout="fixed"`：
   * 招呼语是用户可编辑的长文本，之前不设宽度时它会跟「准入 / 状态」抢空间——编辑过一条
   * 队列条目之后整张表就挤成一团。定宽 + 省略号让每列宽度只由表头决定，内容长短不再影响排版。
   */
  const columns: ColumnsType<ApplyQueueItem> = [
    {
      title: "岗位",
      dataIndex: "job_title",
      width: 220,
      render: (title: string, item) => (
        <Tooltip title={`加入队列于 ${formatDateTime(item.created_at)}`}>
          <Space direction="vertical" size={0} style={{ width: "100%" }}>
            <Button
              type="link"
              className="table-text-link"
              onClick={() => setDetail(item)}
              aria-label={`查看队列条目详情：${title || "岗位已删除"}`}
            >
              {title || "（岗位已删除）"}
            </Button>
            <Space size={4} wrap>
              {item.company && (
                <Typography.Text type="secondary" ellipsis>
                  {item.company}
                </Typography.Text>
              )}
              {item.apply_supported === false && (
                // 和岗位广场上的「采集 / 手动」同一个位置放来源类标签：用户看来源就看这里。
                <Tooltip title="来源不在投递台支持的招聘网站内，无法自动投递；移出队列或到原网站自行投递">
                  <Tag color="red" style={{ marginInlineEnd: 0 }}>
                    来源不支持
                  </Tag>
                </Tooltip>
              )}
            </Space>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: "准入",
      key: "admission",
      width: 140,
      render: (_, item) => <AdmissionTag item={item} />,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 96,
      align: "center",
      render: (value: ApplyQueueItem["status"]) => {
        const meta = QUEUE_STATUS_META[value];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "简历 / 招呼语",
      key: "assets",
      width: 260,
      render: (_, item) => (
        <Space direction="vertical" size={0} style={{ width: "100%" }}>
          <Typography.Text
            type="secondary"
            ellipsis={{ tooltip: item.resume_title || "按默认规则解析" }}
          >
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
      width: 130,
      // 表头与单元格一起右对齐：否则「操作」两字靠左、按钮靠右，看起来像没对齐（用户反馈过）。
      align: "right",
      render: (_, item, index) => (
        <div
          className="apply-queue-actions"
          style={{ display: "flex", justifyContent: "flex-end", marginLeft: "auto" }}
        >
          <Space size={4}>
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
            <Dropdown trigger={["click"]} menu={{ items: rowMenuItems(item) }}>
              <Button
                size="small"
                aria-label={`更多操作 ${item.job_title}`}
                icon={<MoreOutlined />}
              />
            </Dropdown>
          </Space>
        </div>
      ),
    },
  ];

  const rowSelection: TableRowSelection<ApplyQueueItem> = {
    selectedRowKeys: selectedIds,
    onChange: (keys) => setSelectedIds(keys.map(Number)),
    getCheckboxProps: (item) => ({
      // 来源不支持的条目**不可勾选**：勾了也投不出去，不如一开始就不让选（后端还会再拦一次）。
      disabled:
        item.status !== "pending" || item.job_id === null || item.apply_supported === false || busy,
    }),
  };

  if (loading && !data) return <Skeleton active paragraph={{ rows: 5 }} />;

  return (
    <div className="apply-queue-panel">
      {/* 用户反馈过「点进来不知道下一步干什么」：这一段是唯一的入口说明，明确"岗位从哪来、
          在这里做什么、什么时候才真的投出去"。不用弹窗，避免每次进来都要关一次。 */}
      <Alert
        className="apply-queue-flow"
        type="info"
        showIcon
        message="队列里放的是「准备投、但还没投」的岗位"
        description={
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li>
              在<span className="apply-queue-flow-em">「岗位广场」</span>
              打开岗位详情，点<span className="apply-queue-flow-em">「加入投递台」</span>
              把它加进来（从「自动采集」导入的岗位也是同一入口）。
            </li>
            <li>
              在这里核对每个岗位的<span className="apply-queue-flow-em">准入结论</span>
              ：不确定的先回岗位广场做「匹配度分析」，判定有真实缺口的默认不投。
            </li>
            <li>
              需要时逐行点岗位名<span className="apply-queue-flow-em">查看详情或编辑</span>
              ，换一份更贴岗位的简历、改一版招呼语。
            </li>
            <li>
              勾选本轮要投的岗位（
              <span className="apply-queue-flow-em">不勾选＝按顺序投整个队列</span>
              ），再点右上角「开始投递」——在那之前不会打开任何招聘网站。
            </li>
          </ol>
        }
      />

      {/* 来源不支持的条目现在的**唯一**来源是"闸门上线前就已经在队列里"的历史数据。
          写清楚它们是什么、以及两种处理方式，用户才不会在点开始时被一条 409 拦住。 */}
      {unsupportedPending.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={`队列里有 ${unsupportedPending.length} 个岗位不能用投递台自动投递`}
          description={
            <span>
              它们的来源不在投递台支持的招聘网站内（已在「岗位」列标出
              <Tag color="red" style={{ margin: "0 4px" }}>
                来源不支持
              </Tag>
              ）。按「开始投递」投整个队列时会被拦下，请先点行末「更多操作 → 移出队列」把它们清掉；
              只想投其中几个时，勾选要投的岗位再点「开始投递」即可。
            </span>
          }
        />
      )}

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
          disabled={disabled || pendingItems.length === 0}
          onClick={() => void start()}
        >
          开始投递
        </Button>
      </div>

      {items.length === 0 ? (
        <Empty
          description={
            <Space direction="vertical" size={4}>
              <Typography.Text>队列还是空的：先去「岗位广场」挑几个岗位。</Typography.Text>
              <Typography.Text type="secondary">
                在「岗位广场」点岗位名打开详情 → 点「加入投递台」，就能把它加到这里；
                加完之后回到本页，勾选要投的岗位再点「开始投递」。
              </Typography.Text>
            </Space>
          }
        />
      ) : (
        <Table<ApplyQueueItem>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={items}
          pagination={false}
          rowSelection={rowSelection}
          tableLayout="fixed"
          scroll={{ x: 880 }}
          onRow={(record) => ({
            onContextMenu: (event) => {
              event.preventDefault();
              setContextMenu({ x: event.clientX, y: event.clientY, record });
            },
          })}
        />
      )}

      {/* 队列条目的详情：表格里只放得下摘要，招呼语全文、准入结论与时间都在这里看。 */}
      <RecordDetailDrawer
        open={detail !== null}
        title={detail?.job_title || "（岗位已删除）"}
        subtitle={detail?.company}
        tags={detail && <AdmissionTag item={detail} />}
        fields={
          detail
            ? [
                {
                  label: "自动投递",
                  value:
                    detail.apply_supported === false ? (
                      <Tag color="red">来源不支持：请到原网站自行投递</Tag>
                    ) : (
                      "可以：来源在投递台支持的招聘网站内"
                    ),
                },
                {
                  label: "状态",
                  value: (
                    <Tag color={QUEUE_STATUS_META[detail.status].color}>
                      {QUEUE_STATUS_META[detail.status].label}
                    </Tag>
                  ),
                },
                {
                  label: "排队序号",
                  value: `第 ${items.findIndex((i) => i.id === detail.id) + 1} 位`,
                },
                { label: "使用简历", value: detail.resume_title || "按默认规则解析" },
                { label: "加入队列", value: formatDateTime(detail.created_at) },
                { label: "最近更新", value: formatDateTime(detail.updated_at) },
              ]
            : []
        }
        sections={detail ? [{ title: "招呼语", content: detail.greeting || "默认招呼语" }] : []}
        actions={
          detail && (
            <Space>
              <Button
                icon={<EditOutlined />}
                onClick={() => {
                  setEditing(detail);
                  setDetail(null);
                }}
              >
                编辑
              </Button>
              <Button
                danger
                icon={<DeleteOutlined />}
                onClick={() => {
                  void remove(detail);
                  setDetail(null);
                }}
              >
                移出队列
              </Button>
            </Space>
          )
        }
        onClose={() => setDetail(null)}
      />

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

      {contextMenu && (
        <>
          <div
            style={{ position: "fixed", inset: 0, zIndex: 1050 }}
            onClick={() => setContextMenu(null)}
            onContextMenu={(event) => {
              event.preventDefault();
              setContextMenu(null);
            }}
          />
          <Menu
            style={{
              position: "fixed",
              left: contextMenu.x,
              top: contextMenu.y,
              zIndex: 1060,
              minWidth: 150,
              boxShadow: "0 2px 8px rgba(0, 0, 0, 0.15)",
            }}
            items={rowMenuItems(contextMenu.record)}
            onClick={() => setContextMenu(null)}
          />
        </>
      )}
    </div>
  );
}
