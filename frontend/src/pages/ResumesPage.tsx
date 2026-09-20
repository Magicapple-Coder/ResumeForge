/** 简历中心：生成历史列表、收藏、预览与导出。 */
import { StarFilled, StarOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { HTMLAttributes } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  deleteResume,
  getResume,
  listResumes,
  renameResume,
  updateResumeFavorite,
  updateResumeNote,
} from "../api/resumes";
import { diffResume } from "../api/resumeWriting";
import { RowActions, RowContextMenu, type RowActionItem } from "../components/common/RowActions";
import ResumeDetailModal from "../components/ResumeDetailModal";
import ResumeFieldDiffView from "../components/ResumeFieldDiffView";
import { computeFieldDiff } from "../utils/resumeFieldDiff";
import type { DiffViewData } from "../types/resumeFieldDiff";
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
  const [favoriteFilter, setFavoriteFilter] = useState<boolean | undefined>();
  const [hasJobFilter, setHasJobFilter] = useState<boolean | undefined>();
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [favoriteResumeId, setFavoriteResumeId] = useState<number | null>(null);
  const favoriteResumeIdRef = useRef<number | null>(null);
  const [renameTarget, setRenameTarget] = useState<ResumeBrief | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [noteTarget, setNoteTarget] = useState<ResumeBrief | null>(null);
  const [noteValue, setNoteValue] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const [diffBase, setDiffBase] = useState<ResumeBrief | null>(null);
  const [diffAgainstId, setDiffAgainstId] = useState<number | null>(null);
  const [diffResult, setDiffResult] = useState<DiffViewData | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const jobIdParam = searchParams.get("job_id");
  const jobId = jobIdParam && /^\d+$/.test(jobIdParam) ? Number(jobIdParam) : undefined;

  const { data, loading, reload, error } = useApi(
    () =>
      listResumes({
        keyword,
        page,
        page_size: pageSize,
        job_id: jobId,
        favorite: favoriteFilter,
        has_job: hasJobFilter,
      }),
    [keyword, page, pageSize, jobId, favoriteFilter, hasJobFilter],
  );

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  const remove = useCallback(
    async (id: number) => {
      try {
        await deleteResume(id);
        message.success("已移入回收站，可在「回收站」里恢复");
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
      title: "备注",
      dataIndex: "note",
      width: 180,
      render: (value: string) =>
        value ? (
          <Typography.Text ellipsis={{ tooltip: value }} style={{ maxWidth: 180 }}>
            {value}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">-</Typography.Text>
        ),
    },
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
      key: "note",
      label: "编辑备注",
      onClick: () => {
        setNoteTarget(record);
        setNoteValue(record.note ?? "");
      },
    },
    {
      key: "diff",
      label: "版本对比",
      onClick: () => {
        setDiffBase(record);
        setDiffAgainstId(null);
        setDiffResult(null);
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

  const selectDiffAgainst = async (againstId: number) => {
    setDiffAgainstId(againstId);
    if (!diffBase) return;
    setDiffLoading(true);
    try {
      // 同时取两份完整 content 在前端做字段级对比；后端源码 diff 仍保留，用于统计与「查看原始差异」兜底。
      const [base, against, raw] = await Promise.all([
        getResume(diffBase.id),
        getResume(againstId),
        diffResume(diffBase.id, againstId),
      ]);
      const field = computeFieldDiff(base.content, against.content, base.title, against.title);
      setDiffResult({ raw, field });
    } catch (err) {
      message.error(err instanceof Error ? err.message : "版本对比失败");
    } finally {
      setDiffLoading(false);
    }
  };

  const confirmNote = async () => {
    if (!noteTarget || savingNote) return;
    setSavingNote(true);
    try {
      await updateResumeNote(noteTarget.id, noteValue);
      message.success("备注已保存");
      setNoteTarget(null);
      void reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存备注失败");
    } finally {
      setSavingNote(false);
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
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="收藏状态"
          style={{ width: 130 }}
          value={favoriteFilter}
          onChange={(value) => {
            setFavoriteFilter(value);
            setPage(1);
          }}
          options={[
            { value: true, label: "已收藏" },
            { value: false, label: "未收藏" },
          ]}
        />
        <Select
          allowClear
          placeholder="岗位关联"
          style={{ width: 140 }}
          value={hasJobFilter}
          onChange={(value) => {
            setHasJobFilter(value);
            setPage(1);
          }}
          options={[
            { value: true, label: "有目标岗位" },
            { value: false, label: "通用简历" },
          ]}
        />
      </Space>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data?.items ?? []}
        loading={loading}
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
      <Modal
        title="编辑备注"
        open={noteTarget !== null}
        okText="保存"
        confirmLoading={savingNote}
        onCancel={() => {
          if (!savingNote) setNoteTarget(null);
        }}
        onOk={() => void confirmNote()}
      >
        <Input.TextArea
          value={noteValue}
          maxLength={2000}
          showCount
          rows={4}
          placeholder="备注会显示在简历列表里（选填）"
          onChange={(event) => setNoteValue(event.target.value)}
        />
      </Modal>
      <Modal
        title="版本对比"
        open={diffBase !== null}
        width="min(880px, calc(100vw - 24px))"
        footer={null}
        onCancel={() => {
          if (!diffLoading) setDiffBase(null);
        }}
      >
        {diffBase && (
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <Space wrap>
              <Typography.Text>基准版本：</Typography.Text>
              <Typography.Text strong>{diffBase.title}</Typography.Text>
              <Typography.Text type="secondary">对比：</Typography.Text>
              <Select
                style={{ minWidth: 240 }}
                placeholder="选择要对比的版本"
                value={diffAgainstId ?? undefined}
                onChange={(value) => void selectDiffAgainst(value)}
                options={(data?.items ?? [])
                  .filter((item) => item.id !== diffBase.id)
                  .map((item) => ({ value: item.id, label: item.title }))}
              />
            </Space>
            {diffLoading && <Spin />}
            {!diffLoading && diffResult && <ResumeFieldDiffView data={diffResult} />}
            {!diffLoading && !diffResult && (
              <Typography.Text type="secondary">选择一份其它简历后展示三态差异。</Typography.Text>
            )}
          </Space>
        )}
      </Modal>
    </div>
  );
}
