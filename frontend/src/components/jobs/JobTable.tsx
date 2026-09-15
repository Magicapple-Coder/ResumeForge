/** 岗位列表表格、列渲染和分页。 */

import { StarFilled, StarOutlined } from "@ant-design/icons";
import { Button, Popconfirm, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import type { Job, Page } from "../../types";
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
      render: (value: string) => (
        <Typography.Text
          type={value ? undefined : "secondary"}
          ellipsis={value ? { tooltip: value } : undefined}
          style={{ display: "block", maxWidth: 160 }}
        >
          {value || "-"}
        </Typography.Text>
      ),
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
      width: 290,
      render: (_, job) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => onOpenDetail(job)}
          >
            详情
          </Button>
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => onGenerate(job)}
          >
            生成简历
          </Button>
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => onWrite(job)}
          >
            自行编写
          </Button>
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => onViewResumes(job)}
          >
            相关简历
          </Button>
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => onEdit(job)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除该岗位？"
            disabled={batchAction !== null}
            onConfirm={() => onDelete(job)}
          >
            <Button type="link" size="small" danger disabled={batchAction !== null}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
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
