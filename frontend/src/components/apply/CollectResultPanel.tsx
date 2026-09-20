/**
 * 「本次采集结果」：一次采集采到的东西先陈列在这里，**勾选后才进岗位广场**。
 *
 * 为什么不让采集直接入库：采集条件（关键词 + 城市）本来就宽，噪声是常态。直接入库的代价是
 * 用户只能去岗位广场一条条删；"先陈列、再挑选"把这个决定权交还给用户，也让"这次到底采到了
 * 什么"有个地方可看。
 *
 * 导入结果是**逐条**反馈的，而且用常驻提示而不是一条飘过的 toast：勾了 10 条、其中 3 条
 * 岗位广场里已经有了——用户需要知道是哪 3 条、以及为什么，否则他只会看到"导入了 7 条"，
 * 然后去岗位广场里数不出来。
 */
import { LinkOutlined, UploadOutlined } from "@ant-design/icons";
import { Alert, App, Button, Empty, Skeleton, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";
import { importCandidateJobs, listCandidateJobs } from "../../api/candidateJob";
import { useApi } from "../../hooks/useApi";
import type { CandidateJob, CandidateJobImportResult } from "../../types";

interface Props {
  /** 要展示的采集批次；为空表示还没采过，整块不渲染。 */
  taskId: number | null;
  /** 采集/投递正在跑时禁用导入。 */
  disabled?: boolean;
  /** 同一批次的状态或完成时间变化时重新拉取，避免启动时的空结果一直留在页面上。 */
  refreshKey?: string | number;
  /** 导入完成后通知外层（例如让采集记录里的计数跟着更新）。 */
  onImported?: (result: CandidateJobImportResult) => void;
}

const OUTCOME_LABELS: Record<string, string> = {
  duplicate: "岗位广场里已经有这个岗位（已关联到已有那条，没有重复创建）",
  trashed: "岗位广场的「回收站」里已经有同名岗位——先去回收站恢复它，或彻底删除后再导入",
  invalid: "这条没有岗位名，成为不了一个正式岗位",
  missing: "这条候选已经不存在了（可能在别处被删掉）",
};

/** 导入按钮的文案/无障碍名称：带上选中数量，用户不必去数勾了几个。 */
function importLabel(count: number): string {
  return count > 0 ? `导入选中的 ${count} 个岗位` : "导入选中的岗位";
}

export default function CollectResultPanel({
  taskId,
  disabled = false,
  refreshKey = 0,
  onImported,
}: Props) {
  const { message } = App.useApp();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [importing, setImporting] = useState(false);
  const [lastResult, setLastResult] = useState<CandidateJobImportResult | null>(null);

  const { data, loading, error, reload } = useApi<CandidateJob[]>(
    () =>
      taskId
        ? listCandidateJobs({ collectTaskId: taskId, status: "pending" })
        : Promise.resolve([]),
    [taskId, refreshKey],
  );

  useEffect(() => {
    // 切换批次时不能保留上一批的候选 id 或导入反馈，否则可能误导入旧批次条目。
    setSelectedIds([]);
    setLastResult(null);
  }, [taskId]);

  if (!taskId) return null;

  const candidates = data ?? [];

  const doImport = async () => {
    if (selectedIds.length === 0) return;
    setImporting(true);
    try {
      const result = await importCandidateJobs(selectedIds);
      setLastResult(result);
      if (result.imported > 0) {
        message.success(`已导入 ${result.imported} 个岗位到岗位广场`);
      } else {
        message.warning("没有新增岗位，详见下方原因");
      }
      setSelectedIds([]);
      await reload();
      onImported?.(result);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导入失败");
    } finally {
      setImporting(false);
    }
  };

  const columns: ColumnsType<CandidateJob> = [
    {
      title: "岗位",
      dataIndex: "title",
      render: (value: string, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{value || "（未识别到岗位名）"}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.company || "（未识别到公司）"}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "城市",
      dataIndex: "location",
      width: 140,
      render: (value: string) => value || "—",
    },
    {
      title: "薪资",
      dataIndex: "salary",
      width: 130,
      render: (value: string) => value || "—",
    },
    {
      title: "原站",
      dataIndex: "source_url",
      width: 90,
      render: (value: string, row) =>
        value ? (
          <Typography.Link href={value} target="_blank" rel="noopener noreferrer">
            <LinkOutlined /> 查看
          </Typography.Link>
        ) : (
          <Tag>{row.source}</Tag>
        ),
    },
  ];

  const problemResults = (lastResult?.results ?? []).filter((item) => item.outcome !== "imported");

  return (
    <div className="apply-collect-result">
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        <Space size={8} wrap>
          <Typography.Text strong>本次采集结果</Typography.Text>
          <Typography.Text type="secondary">
            勾选要收进岗位广场的岗位，没勾的会留在备选岗位里，之后还能再来挑。
          </Typography.Text>
        </Space>

        {error && <Alert type="error" showIcon message={error} />}

        {lastResult && problemResults.length > 0 && (
          <Alert
            type="warning"
            showIcon
            closable
            onClose={() => setLastResult(null)}
            message={`有 ${problemResults.length} 个岗位没有新建（其余已处理）`}
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {problemResults.map((item) => (
                  <li key={item.candidate_id}>
                    <Typography.Text strong>
                      {item.title || `#${item.candidate_id}`}
                    </Typography.Text>
                    {" — "}
                    {OUTCOME_LABELS[item.outcome] ?? item.outcome}
                  </li>
                ))}
              </ul>
            }
          />
        )}

        {loading && !data ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : candidates.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="这次采集还没有待导入的岗位（可能都已导入，或一条都没采到）"
          />
        ) : (
          <>
            <Table
              rowKey="id"
              size="small"
              columns={columns}
              dataSource={candidates}
              pagination={false}
              rowSelection={{
                selectedRowKeys: selectedIds,
                onChange: (keys) => setSelectedIds(keys as number[]),
              }}
            />
            <Space size={8} wrap>
              <Button
                type="primary"
                icon={<UploadOutlined />}
                loading={importing}
                disabled={disabled || selectedIds.length === 0}
                // 显式 aria-label：antd 会把图标名（"upload"）并进无障碍名称，两字中文按钮
                // 还会被自动插入空格（"全 选"）。不写死名称，界面与测试都容易踩到这两个坑。
                aria-label={importLabel(selectedIds.length)}
                onClick={() => void doImport()}
              >
                {importLabel(selectedIds.length)}
              </Button>
              <Button
                aria-label="全选"
                disabled={disabled || importing}
                onClick={() => setSelectedIds(candidates.map((item) => item.id))}
              >
                全选
              </Button>
              <Button
                aria-label="清空选择"
                disabled={disabled || importing || selectedIds.length === 0}
                onClick={() => setSelectedIds([])}
              >
                清空选择
              </Button>
              <Typography.Text type="secondary">
                导入后到「投递队列」把想要的岗位排进去，再点开始投递。
              </Typography.Text>
            </Space>
          </>
        )}
      </Space>
    </div>
  );
}
