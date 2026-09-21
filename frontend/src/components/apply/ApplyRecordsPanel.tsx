/**
 * 投递记录：按**投递批次**分组展示，并对失败/跳过的条目单独重投。
 *
 * 一次「开始投递」= 一个批次（一次投了好几个岗位时，这几条记录天然同属一组）。
 * 界面把每个批次折叠成一行（批次时间 + 结果统计），点击展开看组内每条记录；
 * 关键词/结果筛选作用在**记录**上——没有命中记录的批次整体不出现。
 *
 * 记录只保存展示快照（岗位、公司、简历名、招呼语），不含完整个人资料——失败条目带上
 * 后端给的中文分类说明与可操作诊断，用户可以直接把这条信息回传给我们定位站点改版。
 */
import {
  DownOutlined,
  RedoOutlined,
  ReloadOutlined,
  RightOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";
import { listRecordBatches, retryRecord } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import { isFromInnerControl } from "../common/recordDetailCore";
import { formatDateTime } from "../../utils/format";
import {
  TASK_ITEM_STATUS_META,
  TASK_STATUS_META,
  failureLabel,
  type ApplyRecord,
  type ApplyRecordBatch,
  type ApplyTask,
  type Page,
} from "../../types";

interface Props {
  disabled: boolean;
  onRetried: (task: ApplyTask) => void;
}

const RESULT_OPTIONS = [
  { value: "success", label: "成功" },
  { value: "failed", label: "失败" },
  { value: "skipped", label: "已跳过" },
];

const BATCH_PAGE_SIZE = 5;

export default function ApplyRecordsPanel({ disabled, onRetried }: Props) {
  const { message } = App.useApp();
  const [keyword, setKeyword] = useState("");
  const [result, setResult] = useState("");
  const [page, setPage] = useState(1);
  const [retrying, setRetrying] = useState<number | null>(null);
  const [detail, setDetail] = useState<ApplyRecord | null>(null);
  // 当前展开的批次 id 集合（分组展示：点击组头展开/收起）。
  const [expanded, setExpanded] = useState<number[]>([]);

  const { data, loading, error, reload } = useApi<Page<ApplyRecordBatch>>(
    () => listRecordBatches({ keyword, result, page, page_size: BATCH_PAGE_SIZE }),
    [keyword, result, page],
  );

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  const retry = async (record: ApplyRecord) => {
    setRetrying(record.id);
    try {
      const task = await retryRecord(record.id);
      message.success("已新建一个重投批次");
      onRetried(task);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重投失败");
    } finally {
      setRetrying(null);
    }
  };

  const toggleBatch = (batchId: number) => {
    setExpanded((prev) =>
      prev.includes(batchId) ? prev.filter((id) => id !== batchId) : [...prev, batchId],
    );
  };

  const recordColumns: ColumnsType<ApplyRecord> = [
    {
      title: "岗位",
      dataIndex: "job_title",
      ellipsis: true,
      render: (title: string, record) => (
        <Space direction="vertical" size={0} style={{ width: "100%" }}>
          <Typography.Text ellipsis>{title || "（岗位已删除）"}</Typography.Text>
          {record.company && (
            <Typography.Text type="secondary" ellipsis>
              {record.company}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: "结果",
      dataIndex: "status",
      width: 80,
      render: (value: ApplyRecord["status"]) => {
        const meta = TASK_ITEM_STATUS_META[value];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "失败分类",
      key: "failure",
      ellipsis: true,
      render: (_, record) =>
        record.failure_category ? (
          <Tag color="red">{failureLabel(record.failure_category, record.failure_label)}</Tag>
        ) : (
          "-"
        ),
    },
    {
      title: "简历",
      dataIndex: "resume_title",
      width: 120,
      ellipsis: true,
      render: (v: string) => v || "-",
    },
    {
      title: "招呼语",
      dataIndex: "greeting",
      ellipsis: true,
      render: (v: string) => v || "（默认）",
    },
    {
      title: "时间",
      key: "finished_at",
      width: 150,
      render: (_, record) => formatDateTime(record.finished_at || record.created_at),
    },
    {
      title: "操作",
      key: "actions",
      width: 80,
      render: (_, record) => (
        <Tooltip title="以该条目为唯一目标重新投递（仍走去重与每日上限）">
          <Button
            size="small"
            icon={<RedoOutlined />}
            loading={retrying === record.id}
            disabled={disabled || record.job_id == null}
            onClick={() => void retry(record)}
          >
            重投
          </Button>
        </Tooltip>
      ),
    },
    {
      title: "详情",
      key: "detail",
      width: 80,
      render: (_, record) => (
        <Button size="small" onClick={() => setDetail(record)}>
          详情
        </Button>
      ),
    },
  ];

  const batches = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="apply-records-panel">
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="搜索岗位 / 公司"
          allowClear
          enterButton={<SearchOutlined />}
          style={{ width: 260 }}
          onSearch={(value) => {
            setKeyword(value);
            setPage(1);
          }}
        />
        <Select
          placeholder="结果"
          allowClear
          style={{ width: 130 }}
          options={RESULT_OPTIONS}
          value={result || undefined}
          onChange={(value) => {
            setResult(value ?? "");
            setPage(1);
          }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void reload()}>
          刷新
        </Button>
        <Typography.Text type="secondary">
          按投递批次分组：一次投出的多个岗位归在一组，点击展开看明细
        </Typography.Text>
      </Space>

      {loading && batches.length === 0 && (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      )}
      {!loading && batches.length === 0 && <Empty description="还没有投递记录" />}

      <div className="apply-records-batches">
        {batches.map((batch) => (
          <BatchGroup
            key={batch.id}
            batch={batch}
            expanded={expanded.includes(batch.id)}
            onToggle={() => toggleBatch(batch.id)}
            recordColumns={recordColumns}
            onOpenDetail={setDetail}
          />
        ))}
      </div>

      {total > BATCH_PAGE_SIZE && (
        <div style={{ textAlign: "right", marginTop: 12 }}>
          <a
            role="button"
            tabIndex={0}
            onClick={(event) => {
              event.preventDefault();
              setPage((prev) => prev + 1);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") setPage((prev) => prev + 1);
            }}
          >
            下一页
          </a>
          <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
            第 {page} / {Math.ceil(total / BATCH_PAGE_SIZE)} 页 · 共 {total} 个批次
          </Typography.Text>
          {page > 1 && (
            <a
              role="button"
              tabIndex={0}
              style={{ marginLeft: 8 }}
              onClick={(event) => {
                event.preventDefault();
                setPage((prev) => Math.max(1, prev - 1));
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") setPage((prev) => Math.max(1, prev - 1));
              }}
            >
              上一页
            </a>
          )}
        </div>
      )}

      <Drawer
        title="投递记录详情"
        placement="right"
        width={480}
        open={detail !== null}
        onClose={() => setDetail(null)}
        destroyOnClose
      >
        {detail && (
          <Descriptions column={1} bordered size="small" colon>
            <Descriptions.Item label="岗位">
              {detail.job_title || "（岗位已删除）"}
              {detail.company ? ` · ${detail.company}` : ""}
            </Descriptions.Item>
            <Descriptions.Item label="简历">{detail.resume_title || "-"}</Descriptions.Item>
            <Descriptions.Item label="招呼语">
              {detail.greeting || "（默认招呼语）"}
            </Descriptions.Item>
            <Descriptions.Item label="结果">
              {TASK_ITEM_STATUS_META[detail.status].label}
            </Descriptions.Item>
            <Descriptions.Item label="失败分类">
              {detail.failure_category
                ? failureLabel(detail.failure_category, detail.failure_label)
                : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="失败信息（含页面 URL / 标题）">
              {detail.failure_detail || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="时间">
              {formatDateTime(detail.finished_at || detail.created_at)}
            </Descriptions.Item>
            <Descriptions.Item label="任务 / 批次">
              {`批次 #${detail.task_id} · 第 ${detail.attempt} 次尝试`}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}

interface BatchGroupProps {
  batch: ApplyRecordBatch;
  expanded: boolean;
  onToggle: () => void;
  recordColumns: ColumnsType<ApplyRecord>;
  onOpenDetail: (record: ApplyRecord) => void;
}

/** 一个批次 = 一个可展开的组：组头是"批次时间 + 统计"，展开后是组内记录表。 */
function BatchGroup({ batch, expanded, onToggle, recordColumns, onOpenDetail }: BatchGroupProps) {
  const statusMeta = TASK_STATUS_META[batch.status];
  return (
    <div className="apply-records-batch" data-testid={`record-batch-${batch.id}`}>
      <button
        type="button"
        className="apply-records-batch-head"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        {expanded ? <DownOutlined /> : <RightOutlined />}
        <Typography.Text strong>批次 #{batch.id}</Typography.Text>
        <Typography.Text type="secondary">
          {formatDateTime(batch.finished_at || batch.created_at)}
        </Typography.Text>
        <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
        <span className="apply-records-batch-stats">
          <Typography.Text type="secondary">
            {`共 ${batch.items.length} 条`}
            {batch.succeeded > 0 && (
              <Typography.Text type="success"> · 成功 {batch.succeeded}</Typography.Text>
            )}
            {batch.failed > 0 && (
              <Typography.Text type="danger"> · 失败 {batch.failed}</Typography.Text>
            )}
            {batch.skipped > 0 && (
              <Typography.Text type="secondary"> · 跳过 {batch.skipped}</Typography.Text>
            )}
          </Typography.Text>
        </span>
      </button>
      {expanded && (
        <div className="apply-records-batch-body">
          <Table<ApplyRecord>
            rowKey="id"
            size="small"
            columns={recordColumns}
            dataSource={batch.items}
            pagination={false}
            scroll={{ y: 320 }}
            // 整行点击也能看详情；行内的「重投」按钮不会被这一层抢走。
            onRow={(record) => ({
              onClick: (event) => {
                if (isFromInnerControl(event)) return;
                onOpenDetail(record);
              },
              style: { cursor: "pointer" },
            })}
            locale={{ emptyText: "该批次没有命中的记录" }}
          />
        </div>
      )}
    </div>
  );
}
