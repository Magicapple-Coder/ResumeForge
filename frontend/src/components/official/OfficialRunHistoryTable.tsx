import { Button, Empty, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import type { OfficialRun } from "../../types";
import { VERDICT_COLORS } from "../../types";
import { formatDateTime } from "../../utils/format";

const { Text } = Typography;

const RUN_STATUS_COLORS: Record<string, string> = {
  running: "processing",
  done: "success",
  stopped: "warning",
  failed: "error",
};

interface Props {
  runs: OfficialRun[];
  loading: boolean;
  selectedRunIds: number[];
  batchAction: "stop" | null;
  onSelectedRunIdsChange: (ids: number[]) => void;
  onBatchStop: () => void;
  onOpenCandidates: (runIds: number[]) => void;
  onOpenReport: (runId: number) => void;
}

export default function OfficialRunHistoryTable({
  runs,
  loading,
  selectedRunIds,
  batchAction,
  onSelectedRunIdsChange,
  onBatchStop,
  onOpenCandidates,
  onOpenReport,
}: Props) {
  const rowSelection: TableRowSelection<OfficialRun> = {
    selectedRowKeys: selectedRunIds,
    onChange: (keys) => onSelectedRunIdsChange(keys.map(Number)),
    getCheckboxProps: () => ({ disabled: batchAction !== null }),
  };

  const columns: ColumnsType<OfficialRun> = [
    {
      title: "时间",
      dataIndex: "started_at",
      width: 150,
      render: (value: string) => <Text style={{ fontSize: 12 }}>{formatDateTime(value)}</Text>,
    },
    {
      title: "公司",
      dataIndex: "site_company",
      width: 140,
      render: (value: string) => value || <Text type="secondary">（已删除）</Text>,
    },
    {
      title: "状态",
      dataIndex: "status_label",
      width: 90,
      render: (value: string, run) => (
        <Tag color={RUN_STATUS_COLORS[run.status] ?? "default"}>{value}</Tag>
      ),
    },
    {
      title: "结论",
      dataIndex: "headline",
      render: (value: string, run) =>
        run.status === "running" ? (
          <Text type="secondary">采集中……</Text>
        ) : (
          <Space direction="vertical" size={0}>
            <Tag color={VERDICT_COLORS[run.verdict]}>{run.verdict_label}</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {value}
            </Text>
          </Space>
        ),
    },
    {
      title: "账目",
      key: "ledger",
      width: 190,
      render: (_, run) => {
        const extras = [
          run.detail_missing > 0 ? `缺正文 ${run.detail_missing} 条` : "",
          run.llm_calls > 0 ? `模型 ${run.llm_calls} 次` : "",
        ].filter(Boolean);
        return (
          <Space direction="vertical" size={0}>
            <Text style={{ fontSize: 12 }}>
              翻页 {run.pages} 次，抓到 {run.collected} 条
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              新入库 {run.stored} 条{extras.length > 0 && `，${extras.join("，")}`}
            </Text>
          </Space>
        );
      },
    },
    {
      title: "操作",
      key: "action",
      width: 100,
      render: (_, run) => (
        <Button size="small" onClick={() => onOpenReport(run.id)}>
          看报告
        </Button>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="small" style={{ width: "100%" }}>
      {runs.length > 0 && (
        <Space wrap>
          <Text type="secondary">已选 {selectedRunIds.length} 条</Text>
          <Button
            size="small"
            disabled={selectedRunIds.length === 0 || batchAction !== null}
            onClick={() => onOpenCandidates(selectedRunIds)}
          >
            查看选中岗位
          </Button>
          <Button
            size="small"
            danger
            loading={batchAction === "stop"}
            disabled={
              selectedRunIds.length === 0 ||
              batchAction !== null ||
              !runs.some((run) => selectedRunIds.includes(run.id) && run.status === "running")
            }
            onClick={onBatchStop}
          >
            停止选中的采集
          </Button>
          <Button
            size="small"
            disabled={selectedRunIds.length === 0 || batchAction !== null}
            onClick={() => onSelectedRunIdsChange([])}
          >
            清空选择
          </Button>
        </Space>
      )}
      <Table<OfficialRun>
        className="official-selection-table"
        rowKey="id"
        rowSelection={rowSelection}
        size="small"
        columns={columns}
        dataSource={runs}
        loading={loading}
        pagination={false}
        locale={{
          emptyText: (
            <Empty
              description={
                <Text type="secondary">
                  还没有采集记录。点上面任意一家公司的「采集」，这里就会留下一条。
                </Text>
              }
            />
          ),
        }}
      />
    </Space>
  );
}
