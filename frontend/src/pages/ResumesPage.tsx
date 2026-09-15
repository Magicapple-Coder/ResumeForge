/** 简历中心：生成历史列表、收藏、预览与导出。 */
import { StarFilled, StarOutlined } from "@ant-design/icons";
import { App, Button, Input, Popconfirm, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { deleteResume, listResumes, updateResumeFavorite } from "../api/resumes";
import ResumeDetailModal from "../components/ResumeDetailModal";
import { RESUME_ENHANCEMENT_LEVELS } from "../config";
import { useApi } from "../hooks/useApi";
import type { ResumeBrief } from "../types";
import { formatDateTime } from "../utils/format";

export default function ResumesPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { message } = App.useApp();
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [favoriteResumeId, setFavoriteResumeId] = useState<number | null>(null);
  const favoriteResumeIdRef = useRef<number | null>(null);
  const jobIdParam = searchParams.get("job_id");
  const jobId = jobIdParam && /^\d+$/.test(jobIdParam) ? Number(jobIdParam) : undefined;

  const { data, loading, reload, error } = useApi(
    () => listResumes({ keyword, page, page_size: pageSize, job_id: jobId }),
    [keyword, page, pageSize, jobId],
  );

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  const remove = useCallback(
    async (id: number) => {
      try {
        await deleteResume(id);
        message.success("已删除");
        void reload();
      } catch (err) {
        message.error(err instanceof Error ? err.message : "删除失败");
      }
    },
    [message, reload],
  );

  const toggleFavorite = useCallback(
    async (record: ResumeBrief) => {
      if (favoriteResumeIdRef.current !== null) return;
      favoriteResumeIdRef.current = record.id;
      setFavoriteResumeId(record.id);
      try {
        await updateResumeFavorite(record.id, !record.favorite);
        await reload();
      } catch (err) {
        message.error(err instanceof Error ? err.message : "更新收藏状态失败");
      } finally {
        favoriteResumeIdRef.current = null;
        setFavoriteResumeId(null);
      }
    },
    [message, reload],
  );

  const columns: ColumnsType<ResumeBrief> = [
    {
      title: "收藏",
      key: "favorite",
      width: 64,
      align: "center",
      render: (_, record) => (
        <Tooltip title={record.favorite ? "取消收藏" : "收藏简历"}>
          <Button
            type="text"
            aria-label={record.favorite ? "取消收藏简历" : "收藏简历"}
            loading={favoriteResumeId === record.id}
            disabled={favoriteResumeId !== null}
            icon={record.favorite ? <StarFilled style={{ color: "#d89614" }} /> : <StarOutlined />}
            onClick={() => void toggleFavorite(record)}
          />
        </Tooltip>
      ),
    },
    {
      title: "简历标题",
      dataIndex: "title",
      render: (_, record) => (
        <Button type="link" className="table-text-link" onClick={() => setPreviewId(record.id)}>
          {record.title}
        </Button>
      ),
    },
    {
      title: "目标岗位",
      key: "job",
      render: (_, record) => (
        <Space>
          {record.job_id ? (
            <Button
              type="link"
              className="table-text-link"
              onClick={() => navigate(`/jobs?job_id=${record.job_id}`)}
            >
              <Tag color="blue">{record.job_title || "-"}</Tag>
            </Button>
          ) : (
            // 无岗位记录的 job_title 存的是求职意向，不能当岗位名显示，
            // 否则通用简历看起来就是一份岗位简历。
            <>
              <Tag color="purple">通用简历</Tag>
              {record.job_title && <Tag>求职意向：{record.job_title}</Tag>}
            </>
          )}
          {record.company && <Tag>{record.company}</Tag>}
        </Space>
      ),
    },
    {
      title: "来源",
      dataIndex: "source",
      width: 100,
      render: (value: ResumeBrief["source"]) => (
        <Tag color={value === "manual" ? "purple" : "blue"}>
          {value === "manual" ? "用户编写" : "AI 生成"}
        </Tag>
      ),
    },
    { title: "模型", dataIndex: "model", width: 150, render: (value) => value || "-" },
    {
      title: "美化拓展",
      key: "enhancement",
      width: 110,
      render: (_, record) => {
        if (!record.enhancement_enabled)
          return <Typography.Text type="secondary">未开启</Typography.Text>;
        const label = RESUME_ENHANCEMENT_LEVELS.find(
          (item) => item.value === record.enhancement_level,
        )?.label;
        return <Tag color="green">{label ?? "已开启"}</Tag>;
      },
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 160,
      render: (value) => formatDateTime(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 140,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => setPreviewId(record.id)}>
            预览 / 导出
          </Button>
          <Popconfirm title="确定删除这条记录？" onConfirm={() => void remove(record.id)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {jobId && (
        <Space style={{ marginBottom: 12 }}>
          <Tag color="blue">按岗位筛选：#{jobId}</Tag>
          <Button type="link" size="small" onClick={() => navigate("/resumes")}>
            清除筛选
          </Button>
        </Space>
      )}
      <Input.Search
        placeholder="搜索简历记录"
        allowClear
        style={{ width: 300, marginBottom: 16 }}
        onSearch={(value) => {
          setKeyword(value);
          setPage(1);
        }}
      />
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data?.items ?? []}
        loading={loading}
        scroll={{ x: 1024 }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条记录`,
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
