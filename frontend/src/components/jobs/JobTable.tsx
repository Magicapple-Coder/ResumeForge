/** 岗位列表表格、列渲染和分页。 */

import { StarFilled, StarOutlined } from "@ant-design/icons";
import { Button, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import type { HTMLAttributes } from "react";
import type { Job, Page } from "../../types";
import { formatDateTime } from "../../utils/format";
import { RowActions, RowContextMenu, type RowActionItem } from "../common/RowActions";
import SkillTags from "../SkillTags";

type BatchAction = "status" | "delete" | null;

// 投递台自动采集写入的 recognition_source 是固定值；手动录入则是一串五花八门的值（含空串）。
// 因此「采集」用相等判断、「手动」取其余，比反过来「source === 手动添加」更稳（source 会随站点增多）。
const RECOGNITION_SOURCE_COLLECT = "岗位采集";

/** 岗位是「自动采集」还是「手动添加」的二分口径，用于职位列的来源角标。 */
function jobSourceKind(job: Job): "collected" | "manual" {
  return job.recognition_source === RECOGNITION_SOURCE_COLLECT ? "collected" : "manual";
}

interface Props {
  jobs: Page<Job> | undefined;
  loading: boolean;
  selectionMode: boolean;
  rowSelection: TableRowSelection<Job>;
  batchAction: BatchAction;
  favoriteJobId: number | null;
  page: number;
  pageSize: number;
  onToggleFavorite: (job: Job) => void;
  onOpenDetail: (job: Job) => void;
  onGenerate: (job: Job) => void;
  onWrite: (job: Job) => void;
  onViewResumes: (job: Job) => void;
  onEdit: (job: Job) => void;
  onDelete: (job: Job) => void;
  onPageChange: (page: number, pageSize: number) => void;
}

const STATUS_COLORS: Record<string, string> = {
  开放中: "green",
  已截止: "default",
  已投递: "blue",
};

export default function JobTable({
  jobs,
  loading,
  selectionMode,
  rowSelection,
  batchAction,
  favoriteJobId,
  page,
  pageSize,
  onToggleFavorite,
  onOpenDetail,
  onGenerate,
  onWrite,
  onViewResumes,
  onEdit,
  onDelete,
  onPageChange,
}: Props) {
  const columns: ColumnsType<Job> = [
    {
      title: "收藏",
      key: "favorite",
      width: 64,
      align: "center",
      render: (_, job) => (
        <Tooltip title={job.favorite ? "取消收藏" : "收藏岗位"}>
          <Button
            type="text"
            size="small"
            aria-label={job.favorite ? "取消收藏" : "收藏岗位"}
            className={`job-favorite-button${job.favorite ? " is-favorite" : ""}`}
            icon={job.favorite ? <StarFilled /> : <StarOutlined />}
            loading={favoriteJobId === job.id}
            disabled={batchAction !== null || favoriteJobId !== null}
            onClick={() => onToggleFavorite(job)}
          />
        </Tooltip>
      ),
    },
    {
      title: "职位",
      dataIndex: "title",
      width: 260,
      // 悬停整格都能看到导入时间：之前 Tooltip 只挂在岗位名那颗链接上，
      // 鼠标停在关键字标签或旁边空白处就没有提示，等于只有一半时候管用。
      render: (_, job) => (
        <Tooltip title={`导入于 ${formatDateTime(job.created_at)}`}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <Button
                type="link"
                className="table-text-link"
                disabled={batchAction !== null}
                onClick={batchAction === null ? () => onOpenDetail(job) : undefined}
              >
                {job.title}
              </Button>
              {jobSourceKind(job) === "collected" ? (
                <Tag color="purple" style={{ marginInlineEnd: 0 }}>
                  采集
                </Tag>
              ) : (
                <Tag style={{ marginInlineEnd: 0 }}>手动</Tag>
              )}
            </div>
            <div style={{ marginTop: 4 }}>
              <SkillTags tags={job.keywords} max={4} />
            </div>
          </div>
        </Tooltip>
      ),
    },
    { title: "公司", dataIndex: "company", width: 130, render: (value) => value || "-" },
    { title: "城市", dataIndex: "location", width: 90, render: (value) => value || "-" },
    { title: "薪资", dataIndex: "salary", width: 130, render: (value) => value || "-" },
    { title: "类型", dataIndex: "job_type", width: 80 },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (value: string) => (
        <Tag color={STATUS_COLORS[value] ?? "default"}>{value || "-"}</Tag>
      ),
    },
    {
      title: "备注",
      dataIndex: "note",
      width: 180,
      render: (_, job) => {
        const hasImages = (job.note_images?.length ?? 0) > 0;
        const text = job.note || "";
        return (
          <div className="job-note-cell">
            <Typography.Text
              type={text ? undefined : "secondary"}
              ellipsis={text ? { tooltip: text } : undefined}
              style={{ display: "block", maxWidth: 160 }}
            >
              {text || "-"}
            </Typography.Text>
            {hasImages && (
              <Tooltip title={`备注里有 ${job.note_images.length} 张图片，打开详情查看`}>
                <Tag color="blue" className="job-note-image-tag">
                  {job.note_images.length} 张图
                </Tag>
              </Tooltip>
            )}
          </div>
        );
      },
    },
    {
      title: "发布时间",
      dataIndex: "posted_at",
      width: 150,
      render: (value: string) => value || "-",
    },
    {
      title: "操作",
      key: "actions",
      width: 170,
      render: (_, job) => (
        <RowActions
          disabled={batchAction !== null}
          primary={primaryActions(job)}
          more={secondaryActions(job)}
        />
      ),
    },
  ];

  /**
   * 行操作分两层，两层**不重叠**：主操作是行上的蓝色链接，「更多」里只放其余操作。
   * 菜单里再出现一遍「详情」会让人以为那是另一个入口（也白白多一次点击）。
   */
  const primaryActions = (job: Job): RowActionItem[] => [
    { key: "detail", label: "详情", onClick: () => onOpenDetail(job) },
    { key: "generate", label: "生成简历", onClick: () => onGenerate(job) },
  ];

  const secondaryActions = (job: Job): RowActionItem[] => [
    { key: "write", label: "自行编写", onClick: () => onWrite(job) },
    { key: "resumes", label: "相关简历", onClick: () => onViewResumes(job) },
    { key: "edit", label: "编辑", onClick: () => onEdit(job) },
    {
      key: "delete",
      label: "删除",
      danger: true,
      confirm: "确定删除该岗位？",
      onClick: () => onDelete(job),
    },
  ];

  /** 整行右键：鼠标不在行内链接上，给完整清单更方便。 */
  const contextActions = (job: Job): RowActionItem[] => [
    ...primaryActions(job),
    ...secondaryActions(job),
  ];

  return (
    <Table
      rowKey="id"
      rowSelection={selectionMode ? rowSelection : undefined}
      columns={columns}
      dataSource={jobs?.items ?? []}
      loading={loading}
      scroll={{ x: 1330 }}
      components={{
        body: {
          // 整行右键即可编辑/删除；批量模式下不拦截右键，避免和选择操作打架。
          row: (props: HTMLAttributes<HTMLTableRowElement>) => {
            const rowKey = String((props as { "data-row-key"?: string })["data-row-key"] ?? "");
            const job = (jobs?.items ?? []).find((item) => String(item.id) === rowKey);
            if (batchAction !== null || !job) return <tr {...props} />;
            return (
              <RowContextMenu items={contextActions(job)}>
                <tr {...props} />
              </RowContextMenu>
            );
          },
        },
      }}
      pagination={{
        current: page,
        pageSize,
        total: jobs?.total ?? 0,
        disabled: batchAction !== null,
        showSizeChanger: true,
        showTotal: (total) => `共 ${total} 个岗位`,
        onChange: onPageChange,
      }}
    />
  );
}
