/**
 * 采集记录：按时间倒序列出每一次采集的**条件与结果**，展开看那次采到的岗位。
 *
 * 采集是个"跑完就看不见过程"的动作——没有这份记录，第二天就不知道上次按什么关键词、哪个城市
 * 采的，也不知道采到了几条、跳过多少重复。所以每条记录至少要说清三件事：什么时候、什么条件、
 * 结果如何（已暂存 / 重复 / 失败原因）。
 */
import { HistoryOutlined } from "@ant-design/icons";
import { Alert, Collapse, Empty, Skeleton, Space, Tag, Typography } from "antd";
import { listApplyTasks } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import { TASK_STATUS_META, type ApplyTask } from "../../types";
import { formatDateTime } from "../../utils/format";
import CollectResultPanel from "./CollectResultPanel";

interface Props {
  /** 采集正在跑时禁用展开里的导入动作。 */
  disabled?: boolean;
  /**
   * 重新拉取的键：采集结束后外层改它即可。
   *
   * 用字符串是为了让调用方能直接拼"批次 id + 状态 + 完成时间"——那个组合变化就代表
   * "有一次采集刚结束"，比拼一堆 state 简单，也不会漏掉刷新。
   */
  refreshKey?: string | number;
}

/**
 * 是否是「补齐详情」批次。
 *
 * 这类批次同样是 ``kind=collect``、也会出现在这份记录里，但它的"条件 / 结果"口径与搜索采集
 * 完全不同——没有关键词/城市，结果也不是"已暂存 N 个"。不区分模式的话，用户会看到一条
 * 「已暂存 0 个 / 采集条件：关键词：xxx」的记录，纯误导。
 */
function isBackfillTask(task: ApplyTask): boolean {
  const ids = task.config?.backfill_job_ids;
  return Array.isArray(ids) && ids.length > 0;
}

/** 把批次 config 里的关键词/城市读成一行可读文字；补详情批次没有"采集条件"可显示。 */
function conditionText(task: ApplyTask): string {
  if (isBackfillTask(task)) return "";
  const keywords = Array.isArray(task.config?.keywords)
    ? (task.config.keywords as unknown[]).filter((item): item is string => typeof item === "string")
    : [];
  const city = typeof task.config?.city === "string" ? task.config.city : "";
  const parts: string[] = [];
  if (keywords.length > 0) parts.push(`关键词：${keywords.join("、")}`);
  if (city.trim()) parts.push(`城市：${city.trim()}`);
  return parts.length > 0 ? parts.join("；") : "（未记录采集条件）";
}

function resultText(task: ApplyTask): string {
  if (isBackfillTask(task)) {
    // 后端已经把补详情的收尾文案写好并存在 ``message``（补到几条 / 跳过几条 / 为什么），能用就直接
    // 用，绝不再造一套不同措辞。message 为空（异常路径）时退回用计数拼一句。
    const message = (task.message ?? "").trim();
    if (message) return message;
    // 兜底必须读 ``task.succeeded`` / ``task.skipped``——这是**进度条用的同一个数据源**，由
    // ``_update_task_progress`` 逐条同步，所以「正常完成 / 中途停止 / 部分失败」三种情况都对。
    // 反面教材：以前读 ``config.backfilled`` / ``config.backfill_skipped``，而那份账目只在
    // ``run()`` **正常收尾**时才写；用户中途停止走的是另一条路径、根本不写它，于是明明已经补好了
    // N 条（JD 是逐条 commit 的），面板却显示「已补齐 0 条」——给用户看了个不真实的数字。
    // 补详情模式下 collected/skipped 恒为 0，故 succeeded 即 backfilled、skipped 即 backfill_skipped。
    const backfilled = task.succeeded ?? 0;
    const skipped = task.skipped ?? 0;
    const parts = [`已补齐 ${backfilled} 条`];
    if (skipped) parts.push(`跳过 ${skipped} 条`);
    if (task.failed) parts.push(`失败 ${task.failed} 条`);
    return parts.join("，");
  }
  const parts = [`已暂存 ${task.succeeded ?? 0} 个`];
  if (task.skipped) parts.push(`重复 ${task.skipped} 个`);
  // 筛选掉的条数也要出现在摘要行里：只写"已暂存 N 个"，用户会以为采到的全都在这儿了。
  const filtered = Number(task.config?.filtered_out) || 0;
  if (filtered) parts.push(`筛选掉 ${filtered} 个`);
  if (task.failed) parts.push(`失败 ${task.failed} 个`);
  return parts.join("，");
}

export default function CollectRecordsPanel({ disabled = false, refreshKey = 0 }: Props) {
  const { data, loading, error } = useApi<ApplyTask[]>(
    () => listApplyTasks({ kind: "collect", limit: 30 }),
    [refreshKey],
  );

  if (error) return <Alert type="error" showIcon message={error} />;
  if (loading && !data) return <Skeleton active paragraph={{ rows: 5 }} />;

  const records = data ?? [];
  if (records.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="还没有采集记录。到「自动采集」页签设置条件并点「开始采集」，这里就会出现每一次的记录。"
      />
    );
  }

  return (
    <Collapse
      className="apply-collect-records"
      items={records.map((record) => {
        const meta = TASK_STATUS_META[record.status];
        const condition = conditionText(record);
        return {
          key: String(record.id),
          label: (
            <Space size={8} wrap>
              <HistoryOutlined />
              <Typography.Text strong>
                {formatDateTime(record.finished_at || record.created_at)}
              </Typography.Text>
              <Tag color={meta?.color}>{meta?.label ?? record.status}</Tag>
              {condition && <Typography.Text type="secondary">{condition}</Typography.Text>}
              <Typography.Text>{resultText(record)}</Typography.Text>
            </Space>
          ),
          children: (
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              {record.message && <Alert type="info" showIcon message={record.message} />}
              <CollectResultPanel taskId={record.id} disabled={disabled} />
            </Space>
          ),
        };
      })}
    />
  );
}
