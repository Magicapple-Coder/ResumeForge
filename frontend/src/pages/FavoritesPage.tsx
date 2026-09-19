/** 收藏夹：集中查看收藏的岗位与简历。 */
import { FileTextOutlined, SearchOutlined, StarFilled } from "@ant-design/icons";
import { App, Button, Empty, Space, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { HTMLAttributes } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listJobs, updateJob } from "../api/jobs";
import { listResumes, updateResumeFavorite } from "../api/resumes";
import { RowActions, RowContextMenu, type RowActionItem } from "../components/common/RowActions";
import ResumeDetailModal from "../components/ResumeDetailModal";
import { useApi } from "../hooks/useApi";
import type { Job, Page, ResumeBrief } from "../types";
import { formatDateTime } from "../utils/format";

type FavoriteKind = "jobs" | "resumes";
type FavoritePage =
  { kind: "jobs"; page: Page<Job> } | { kind: "resumes"; page: Page<ResumeBrief> };

export default function FavoritesPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [kind, setKind] = useState<FavoriteKind>("jobs");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [updatingKey, setUpdatingKey] = useState("");
  const updatingKeyRef = useRef("");

  const { data, loading, error, reload } = useApi<FavoritePage>(async () => {
    if (kind === "jobs") {
      return { kind, page: await listJobs({ favorite: true, page, page_size: pageSize }) };
    }
    return { kind, page: await listResumes({ favorite: true, page, page_size: pageSize }) };
  }, [kind, page, pageSize]);

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  const removeJobFavorite = useCallback(
    async (job: Job) => {
      const key = `job-${job.id}`;
      if (updatingKeyRef.current) return;
      updatingKeyRef.current = key;
      setUpdatingKey(key);
      try {
        await updateJob(job.id, { favorite: false });
        await reload();
      } catch (err) {
        message.error(err instanceof Error ? err.message : "取消收藏失败");
      } finally {
        updatingKeyRef.current = "";
        setUpdatingKey("");
      }
    },
    [message, reload],
  );

  const removeResumeFavorite = useCallback(
    async (resume: ResumeBrief) => {
      const key = `resume-${resume.id}`;
      if (updatingKeyRef.current) return;
      updatingKeyRef.current = key;
      setUpdatingKey(key);
      try {
        await updateResumeFavorite(resume.id, false);
        await reload();
      } catch (err) {
        message.error(err instanceof Error ? err.message : "取消收藏失败");
      } finally {
        updatingKeyRef.current = "";
        setUpdatingKey("");
      }
    },
    [message, reload],
  );

  const favoriteButton = (key: string, onClick: () => void) => (
    <Tooltip title="取消收藏">
      <Button
        type="text"
        aria-label="取消收藏"
        loading={updatingKey === key}
        disabled={Boolean(updatingKey)}
        icon={<StarFilled style={{ color: "#d89614" }} />}
        onClick={onClick}
      />
    </Tooltip>
  );

  /**
   * 「更多」菜单里**不放**「取消收藏」：行上那颗金色星标就是它，菜单里再来一项
   * 只会让人怀疑两者是不是不同的操作。
   */
  const secondaryActions = (item: Job | ResumeBrief): RowActionItem[] =>
    kind === "jobs"
      ? [
          {
            key: "open",
            label: "打开岗位详情",
            onClick: () => navigate(`/jobs?job_id=${item.id}`),
          },
        ]
      : [{ key: "preview", label: "预览 / 导出", onClick: () => setPreviewId(item.id) }];

  /** 整行右键：鼠标不在星标上，补上取消收藏，一次右键就能做完。 */
  const contextActions = (item: Job | ResumeBrief): RowActionItem[] => [
    ...secondaryActions(item),
    {
      key: "unfavorite",
      label: "取消收藏",
      onClick: () =>
        kind === "jobs"
          ? void removeJobFavorite(item as Job)
          : void removeResumeFavorite(item as ResumeBrief),
    },
  ];

  const jobColumns: ColumnsType<Job> = [
    {
      title: "岗位",
      dataIndex: "title",
      render: (_, job) => (
        <Tooltip title={`导入于 ${formatDateTime(job.created_at)}`}>
          <Button
            type="link"
            className="table-text-link"
            onClick={() => navigate(`/jobs?job_id=${job.id}`)}
          >
            {job.title}
          </Button>
        </Tooltip>
      ),
    },
    { title: "公司", dataIndex: "company", width: 180, render: (value) => value || "-" },
    { title: "地点", dataIndex: "location", width: 120, render: (value) => value || "-" },
    { title: "发布时间", dataIndex: "posted_at", width: 150, render: (value) => value || "-" },
    {
      title: "操作",
      width: 130,
      align: "center",
      render: (_, job) => (
        <Space size={4}>
          {favoriteButton(`job-${job.id}`, () => void removeJobFavorite(job))}
          <RowActions more={secondaryActions(job)} />
        </Space>
      ),
    },
  ];

  const resumeColumns: ColumnsType<ResumeBrief> = [
    {
      title: "简历",
      dataIndex: "title",
      render: (_, resume) => (
        <Button type="link" className="table-text-link" onClick={() => setPreviewId(resume.id)}>
          {resume.title}
        </Button>
      ),
    },
    {
      title: "目标岗位",
      width: 220,
      render: (_, resume) => (
        <Space size={4}>
          <Tag color="blue">{resume.job_title || "-"}</Tag>
          {resume.company && <Tag>{resume.company}</Tag>}
        </Space>
      ),
    },
    {
      title: "来源",
      dataIndex: "source",
      width: 110,
      render: (value: ResumeBrief["source"]) => (value === "manual" ? "用户编写" : "AI 生成"),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 160,
      render: (value) => formatDateTime(value),
    },
    {
      title: "操作",
      width: 130,
      align: "center",
      render: (_, resume) => (
        <Space size={4}>
          {favoriteButton(`resume-${resume.id}`, () => void removeResumeFavorite(resume))}
          <RowActions more={secondaryActions(resume)} />
        </Space>
      ),
    },
  ];

  const currentPage = data?.kind === kind ? data.page : undefined;
  const items = currentPage?.items ?? [];

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Typography.Title level={3} style={{ marginBottom: 4 }}>
          收藏夹
        </Typography.Title>
        <Typography.Text type="secondary">集中查看你关注的招聘信息和简历版本。</Typography.Text>
      </div>
      <Tabs
        activeKey={kind}
        onChange={(value) => {
          setKind(value as FavoriteKind);
          setPage(1);
        }}
        items={[
          {
            key: "jobs",
            label: (
              <Space size={6}>
                <SearchOutlined />
                招聘信息
              </Space>
            ),
          },
          {
            key: "resumes",
            label: (
              <Space size={6}>
                <FileTextOutlined />
                简历
              </Space>
            ),
          },
        ]}
      />
      <Table<Job | ResumeBrief>
        rowKey="id"
        columns={(kind === "jobs" ? jobColumns : resumeColumns) as ColumnsType<Job | ResumeBrief>}
        dataSource={items}
        loading={loading}
        locale={{
          emptyText: <Empty description={kind === "jobs" ? "暂无收藏岗位" : "暂无收藏简历"} />,
        }}
        // 简历列的固定宽度加起来约 620px，比岗位列更窄，在普通窗口里根本不会横向溢出；
        // 硬套 `x: 760` 会在「简历」页签下画出一条用不上的横向滚动条。岗位列更宽，仍保留兜底。
        scroll={kind === "jobs" ? { x: 760 } : undefined}
        components={{
          body: {
            row: (props: HTMLAttributes<HTMLTableRowElement>) => {
              const rowKey = String((props as { "data-row-key"?: string })["data-row-key"] ?? "");
              const item = items.find((entry) => String(entry.id) === rowKey);
              if (!item) return <tr {...props} />;
              return (
                <RowContextMenu items={contextActions(item)}>
                  <tr {...props} />
                </RowContextMenu>
              );
            },
          },
        }}
        pagination={{
          current: page,
          pageSize,
          total: currentPage?.total ?? 0,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 项收藏`,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
      />
      <ResumeDetailModal recordId={previewId} onClose={() => setPreviewId(null)} />
    </div>
  );
}
