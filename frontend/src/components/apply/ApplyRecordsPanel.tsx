/**
 * 投递记录：按结果检索历史条目，并对失败/跳过的条目单独重投。
 *
 * 记录只保存展示快照（岗位、公司、简历名、招呼语），不含完整个人资料——失败条目带上后端给的
 * 中文分类说明与可操作诊断，用户可以直接把这条信息回传给我们定位站点改版。
 */
import { RedoOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";
import { listRecords, retryRecord } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import { formatDateTime } from "../../utils/format";
import {
  TASK_ITEM_STATUS_META,
  failureLabel,
  type ApplyRecord,
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

export default function ApplyRecordsPanel({ disabled, onRetried }: Props) {
  const { message } = App.useApp();
  const [keyword, setKeyword] = useState("");
  const [result, setResult] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [retrying, setRetrying] = useState<number | null>(null);
  const [detail, setDetail] = useState<ApplyRecord | null>(null);

  const { data, loading, error, reload } = useApi<Page<ApplyRecord>>(
    () => listRecords({ keyword, result, page, page_size: pageSize }),
    [keyword, result, page, pageSize],
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

  const columns: ColumnsType<ApplyRecord> = [
    {
      title: "岗位",
      dataIndex: "job_title",
      ellipsis: true,
      render: (title: string, record) => (
        <Space direction="vertical" size={0} style={{ width: "100%" }}>
          <Typography.Text ellipsis title={undefined}>
            {title || "（岗位已删除）"}
          </Typography.Text>
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
      </Space>

      <Table<ApplyRecord>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={data?.items ?? []}
        scroll={{ y: 480 }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
        locale={{ emptyText: "还没有投递记录" }}
      />

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
