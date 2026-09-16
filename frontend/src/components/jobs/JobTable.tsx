/** 岗位列表表格、列渲染和分页。 */

import { StarFilled, StarOutlined } from "@ant-design/icons";
import { Button, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import type { HTMLAttributes } from "react";
import type { Job, Page } from "../../types";
import { RowActions, RowContextMenu, type RowActionItem } from "../common/RowActions";
import SkillTags from "../SkillTags";

type BatchAction = "status" | "delete" | null;

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
      render: (_, job) => (
        <div>
          <Button
            type="link"
            className="table-text-link"
            disabled={batchAction !== null}
            onClick={batchAction === null ? () => onOpenDetail(job) : undefined}
          >
            {job.title}
          </Button>
          <div style={{ marginTop: 4 }}>
            <SkillTags tags={job.keywords} max={4} />
          </div>
        </div>
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
          // 只留最常用的两个：其余（含删除）收进「更多」，避免一排红色按钮挤在一起。
          primary={[
            { key: "detail", label: "详情", onClick: () => onOpenDetail(job) },
            { key: "generate", label: "生成简历", onClick: () => onGenerate(job) },
          ]}
          more={actionsFor(job)}
        />
      ),
    },
  ];

  /** 行的完整操作清单：三点菜单与整行右键共用同一份。 */
  const actionsFor = (job: Job): RowActionItem[] => [
    { key: "detail", label: "查看详情", onClick: () => onOpenDetail(job) },
    { key: "generate", label: "生成简历", onClick: () => onGenerate(job) },
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
              <RowContextMenu items={actionsFor(job)}>
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
