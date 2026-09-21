/**
 * 执行进度面板：全局计数 + 逐岗位状态机 + 熔断警示 + 暂停/停止控制。
 *
 * 两个刻意的选择：
 * - **不用百分比进度条**，只显示「已处理 N/M」——总数在运行时可能变化（队列被改、岗位被删），
 *   百分比会给人一个并不准确的确定性；设计也明确禁止渲染任何百分比（§9 ⑩）。
 * - 暂停/停止按钮**常驻**（按状态置灰而不是隐藏），用户不用去别处找停止入口。
 */
import { PauseOutlined, PlayCircleOutlined, StopOutlined } from "@ant-design/icons";
import { Alert, Button, Descriptions, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { ReactNode } from "react";
import {
  TASK_ITEM_STATUS_META,
  TASK_STATUS_META,
  failureLabel,
  stepLabel,
  type ApplyTaskDetail,
  type ApplyTaskItem,
  type TaskStatus,
} from "../../types";
import { isActiveTaskStatus as isActive } from "../../hooks/useTaskPolling";
import { formatDateTime } from "../../utils/format";

interface Props {
  task: ApplyTaskDetail;
  busy: boolean;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
}

/** 状态 → 顶部提示条的类型：熔断要醒目（error），暂停用 warning，其余用 info/success。 */
function alertType(status: TaskStatus): "error" | "warning" | "info" | "success" {
  if (status === "breaker_paused" || status === "failed") return "error";
  if (status === "paused") return "warning";
  if (status === "completed") return "success";
  return "info";
}

const STOP_REASON_LABELS: Record<string, string> = {
  user: "用户停止",
  breaker: "连续失败熔断",
  done: "已完成",
  error: "发生错误",
};

const KIND_LABELS: Record<string, string> = {
  apply: "投递批次",
  collect: "采集批次",
};

export default function ApplyProgressPanel({ task, busy, onPause, onResume, onStop }: Props) {
  const statusMeta = TASK_STATUS_META[task.status];
  const active = isActive(task.status);
  const canResume = task.status === "paused" || task.status === "breaker_paused";
  const alertMessage =
    task.message ||
    (task.stop_reason ? (STOP_REASON_LABELS[task.stop_reason] ?? task.stop_reason) : "");

  const columns: ColumnsType<ApplyTaskItem> = [
    {
      title: "岗位",
      dataIndex: "job_title",
      render: (title: string, item) => (
        <Space direction="vertical" size={0}>
          <Typography.Text>{title || "（岗位已删除）"}</Typography.Text>
          {item.company && (
            <Typography.Text type="secondary" className="apply-progress-company">
              {item.company}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 96,
      render: (value: ApplyTaskItem["status"]) => {
        const meta = TASK_ITEM_STATUS_META[value];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "失败分类",
      dataIndex: "failure_category",
      width: 180,
      render: (value: string) => (value ? <Tag color="red">{failureLabel(value)}</Tag> : "-"),
    },
    { title: "尝试", dataIndex: "attempt", width: 64 },
  ];

  const expandedRowRender = (item: ApplyTaskItem): ReactNode => (
    <Descriptions size="small" column={1} className="apply-progress-detail">
      <Descriptions.Item label="当前步骤">{stepLabel(task.current_step)}</Descriptions.Item>
      <Descriptions.Item label="使用简历">
        {item.resume_title || "按默认规则解析"}
      </Descriptions.Item>
      <Descriptions.Item label="招呼语">{item.greeting || "（使用默认招呼语）"}</Descriptions.Item>
      {item.failure_detail && (
        // 跳过的条目也会写明细（例如「按『同公司只投一个岗位』跳过」），那是**跳过原因**
        // 不是失败诊断——同一个字段两种含义时，标签得跟着状态走，否则用户会以为出错了。
        <Descriptions.Item label={item.status === "skipped" ? "跳过原因" : "诊断信息"}>
          {item.failure_detail}
        </Descriptions.Item>
      )}
      <Descriptions.Item label="开始时间">
        {formatDateTime(item.started_at ?? undefined)}
      </Descriptions.Item>
      <Descriptions.Item label="结束时间">
        {formatDateTime(item.finished_at ?? undefined)}
      </Descriptions.Item>
    </Descriptions>
  );

  return (
    <section className="apply-progress-panel" aria-live="polite">
      <div className="apply-progress-head">
        <Space wrap size={12} align="center">
          <Typography.Text strong>{KIND_LABELS[task.kind] ?? "执行批次"}</Typography.Text>
          <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
          {active && (
            <Typography.Text type="secondary">
              当前步骤：{stepLabel(task.current_step)}
            </Typography.Text>
          )}
        </Space>
        <Space wrap>
          <Button
            icon={<PauseOutlined />}
            disabled={!active || task.status !== "running" || busy}
            onClick={onPause}
          >
            暂停
          </Button>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            disabled={!canResume || busy}
            onClick={onResume}
          >
            继续
          </Button>
          <Button danger icon={<StopOutlined />} disabled={!active || busy} onClick={onStop}>
            停止
          </Button>
        </Space>
      </div>

      {alertMessage && (
        <Alert
          type={alertType(task.status)}
          showIcon
          message={alertMessage}
          className="apply-progress-alert"
        />
      )}

      <Space wrap size={16} className="apply-progress-counts">
        <Typography.Text>
          已处理 <Typography.Text strong>{task.processed}</Typography.Text> / {task.total}
        </Typography.Text>
        <Typography.Text type="success">成功 {task.succeeded}</Typography.Text>
        <Typography.Text type="danger">失败 {task.failed}</Typography.Text>
        <Typography.Text type="secondary">已跳过 {task.skipped}</Typography.Text>
      </Space>

      {task.items.length > 0 ? (
        <Table<ApplyTaskItem>
          className="apply-progress-table"
          size="small"
          rowKey="id"
          columns={columns}
          dataSource={task.items}
          pagination={false}
          expandable={{ expandedRowRender }}
          scroll={{ x: "max-content" }}
        />
      ) : (
        <Typography.Paragraph type="secondary" className="apply-progress-empty">
          {task.kind === "collect"
            ? "采集批次不逐条列出岗位，新增数量见上方计数。"
            : "本批次没有可展示的岗位条目。"}
        </Typography.Paragraph>
      )}
    </section>
  );
}
