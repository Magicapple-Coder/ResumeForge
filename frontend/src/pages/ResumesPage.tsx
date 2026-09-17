/** 简历中心：生成历史列表、收藏、预览与导出。 */
import { StarFilled, StarOutlined } from "@ant-design/icons";
import { App, Button, Input, Modal, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { HTMLAttributes } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { deleteResume, listResumes, renameResume, updateResumeFavorite } from "../api/resumes";
import { RowActions, RowContextMenu, type RowActionItem } from "../components/common/RowActions";
import ResumeDetailModal from "../components/ResumeDetailModal";
import { RESUME_ENHANCEMENT_LEVELS, enhancementLevelDescription } from "../config";
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
  const [renameTarget, setRenameTarget] = useState<ResumeBrief | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renaming, setRenaming] = useState(false);
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
              <Tooltip title="不关联岗位、可投递多个方向的简历">
                <Tag color="purple">通用简历</Tag>
              </Tooltip>
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
        const level = RESUME_ENHANCEMENT_LEVELS.find(
          (item) => item.value === record.enhancement_level,
        );
        // "均衡"这种词单看说明不了什么；悬停给出这一档到底做了什么——和生成弹窗里
        // 用的是同一份文案，通用简历的"深度"档说法也由它区分。
        return (
          <Tooltip
            title={
              record.enhancement_level
                ? enhancementLevelDescription(record.enhancement_level, !record.job_id)
                : "已开启经历美化拓展"
            }
          >
            <Tag color="green">{level?.label ?? "已开启"}</Tag>
          </Tooltip>
        );
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
      width: 150,
      render: (_, record) => (
        <RowActions primary={primaryActions(record)} more={secondaryActions(record)} />
      ),
    },
  ];

  /**
   * 行操作分两层，两层**不重叠**：主操作是行上的蓝色链接，「更多」里只放其余操作。
   * 菜单里再出现一遍「预览 / 导出」会让人以为那是另一个入口。
   */
  const primaryActions = (record: ResumeBrief): RowActionItem[] => [
    { key: "preview", label: "预览 / 导出", onClick: () => setPreviewId(record.id) },
  ];

  const secondaryActions = (record: ResumeBrief): RowActionItem[] => [
    {
      key: "rename",
      label: "重命名",
      onClick: () => {
        setRenameTarget(record);
        setRenameValue(record.title);
      },
    },
    {
      key: "favorite",
      label: record.favorite ? "取消收藏" : "收藏",
      onClick: () => void toggleFavorite(record),
    },
    {
      key: "delete",
      label: "删除",
      danger: true,
      confirm: "确定删除这条记录？",
      onClick: () => void remove(record.id),
    },
  ];

  /** 整行右键：鼠标不在行内链接上，给完整清单更方便。 */
  const contextActions = (record: ResumeBrief): RowActionItem[] => [
    ...primaryActions(record),
    ...secondaryActions(record),
  ];

  const confirmRename = async () => {
    if (!renameTarget || renaming) return;
    const title = renameValue.trim();
    if (!title) {
      message.warning("简历名称不能为空");
      return;
    }
    setRenaming(true);
    try {
      await renameResume(renameTarget.id, title);
      message.success("已重命名");
      setRenameTarget(null);
      void reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重命名失败");
    } finally {
      setRenaming(false);
    }
  };

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
        components={{
          body: {
            // 整行右键即可重命名、收藏或删除，不必先找到右侧的按钮。
            row: (props: HTMLAttributes<HTMLTableRowElement>) => {
              const rowKey = String((props as { "data-row-key"?: string })["data-row-key"] ?? "");
              const record = (data?.items ?? []).find((item) => String(item.id) === rowKey);
              if (!record) return <tr {...props} />;
              return (
                <RowContextMenu items={contextActions(record)}>
                  <tr {...props} />
                </RowContextMenu>
              );
            },
          },
        }}
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
      <Modal
        title="重命名简历"
        open={renameTarget !== null}
        okText="保存"
        confirmLoading={renaming}
        onCancel={() => {
          if (!renaming) setRenameTarget(null);
        }}
        onOk={() => void confirmRename()}
      >
        <Input
          value={renameValue}
          maxLength={256}
          placeholder="简历名称"
          onChange={(event) => setRenameValue(event.target.value)}
        />
      </Modal>
    </div>
  );
}
