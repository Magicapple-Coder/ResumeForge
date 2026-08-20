/** 岗位广场：搜索筛选、手动添加、详情与生成简历入口。 */
import {
  CheckSquareOutlined,
  CheckOutlined,
  ClearOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  PlusOutlined,
  StarFilled,
  StarOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  batchDeleteJobs,
  batchUpdateJobStatus,
  deleteJob,
  getJob,
  listJobs,
  updateJob,
} from "../api/jobs";
import GenerateResumeModal from "../components/GenerateResumeModal";
import JobAnalysisModal from "../components/JobAnalysisModal";
import JobDetailDrawer from "../components/JobDetailDrawer";
import JobFormModal from "../components/JobFormModal";
import ManualResumeModal from "../components/ManualResumeModal";
import SkillTags from "../components/SkillTags";
import { useApi } from "../hooks/useApi";
import type { Job } from "../types";

const JOB_TYPE_OPTIONS = ["校招", "实习", "社招", "其他"].map((value) => ({ value, label: value }));
const STATUS_OPTIONS = ["开放中", "已截止", "已投递"].map((value) => ({ value, label: value }));
const STATUS_COLORS: Record<string, string> = {
  开放中: "green",
  已截止: "default",
  已投递: "blue",
};

type BatchAction = "status" | "delete" | null;

export default function JobsPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { message } = App.useApp();

  const [keyword, setKeyword] = useState(searchParams.get("keyword") ?? "");
  const [jobType, setJobType] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [detailJob, setDetailJob] = useState<Job | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<Job | null>(null);
  const [generateJob, setGenerateJob] = useState<Job | null>(null);
  const [manualResumeJob, setManualResumeJob] = useState<Job | null>(null);
  const [analysisJob, setAnalysisJob] = useState<Job | null>(null);
  const [selectedJobIds, setSelectedJobIds] = useState<number[]>([]);
  const [batchStatus, setBatchStatus] = useState<string>();
  const [batchAction, setBatchAction] = useState<BatchAction>(null);
  const [favoriteJobId, setFavoriteJobId] = useState<number | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const linkedJobId = Number(searchParams.get("job_id")) || null;
  const [openedLinkedJobId, setOpenedLinkedJobId] = useState<number | null>(null);

  const {
    data: jobs,
    loading,
    reload,
    error,
  } = useApi(
    () => listJobs({ keyword, job_type: jobType, status, page, page_size: pageSize }),
    [keyword, jobType, status, page, pageSize],
  );

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  useEffect(() => {
    if (!linkedJobId || openedLinkedJobId === linkedJobId || loading) return;
    const listedJob = jobs?.items.find((item) => item.id === linkedJobId);
    if (listedJob) {
      setDetailJob(listedJob);
      setOpenedLinkedJobId(linkedJobId);
      return;
    }
    setOpenedLinkedJobId(linkedJobId);
    void getJob(linkedJobId)
      .then(setDetailJob)
      .catch((err) => message.error(err instanceof Error ? err.message : "岗位不存在或已被删除"));
  }, [jobs, linkedJobId, loading, message, openedLinkedJobId]);

  const removeJob = useCallback(
    async (id: number) => {
      try {
        await deleteJob(id);
        setSelectedJobIds((current) => current.filter((jobId) => jobId !== id));
        message.success("岗位已删除");
        void reload();
      } catch (err) {
        message.error(err instanceof Error ? err.message : "删除失败");
      }
    },
    [message, reload],
  );

  const toggleFavorite = useCallback(
    async (job: Job) => {
      if (batchAction !== null || favoriteJobId !== null) return;
      setFavoriteJobId(job.id);
      try {
        const updated = await updateJob(job.id, { favorite: !job.favorite });
        setDetailJob((current) => (current?.id === job.id ? updated : current));
        await reload();
      } catch (err) {
        message.error(err instanceof Error ? err.message : "更新收藏状态失败");
      } finally {
        setFavoriteJobId(null);
      }
    },
    [batchAction, favoriteJobId, message, reload],
  );

  const applyBatchStatus = async () => {
    if (selectedJobIds.length === 0) {
      message.warning("请先选择岗位");
      return;
    }
    if (!batchStatus) {
      message.warning("请选择要设置的状态");
      return;
    }

    const jobIds = [...selectedJobIds];
    const nextStatus = batchStatus;
    setBatchAction("status");
    try {
      const result = await batchUpdateJobStatus({ job_ids: jobIds, status: nextStatus });
      setSelectedJobIds([]);
      setBatchStatus(undefined);
      setDetailJob((current) =>
        current && jobIds.includes(current.id) ? { ...current, status: nextStatus } : current,
      );
      await reload();
      message.success(`已更新 ${result.updated} 个岗位的状态`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "批量更新状态失败");
    } finally {
      setBatchAction(null);
    }
  };

  const removeSelectedJobs = async () => {
    if (selectedJobIds.length === 0) {
      message.warning("请先选择岗位");
      return;
    }

    const jobIds = [...selectedJobIds];
    setBatchAction("delete");
    try {
      const result = await batchDeleteJobs({ job_ids: jobIds });
      setSelectedJobIds([]);
      setBatchStatus(undefined);
      setDetailJob((current) => (current && jobIds.includes(current.id) ? null : current));
      if (page !== 1) setPage(1);
      await reload();
      message.success(`已删除 ${result.deleted} 个岗位`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "批量删除失败");
    } finally {
      setBatchAction(null);
    }
  };

  const exitSelectionMode = () => {
    if (batchAction !== null) return;
    setSelectionMode(false);
    setSelectedJobIds([]);
    setBatchStatus(undefined);
  };

  const rowSelection: TableRowSelection<Job> = {
    selectedRowKeys: selectedJobIds,
    preserveSelectedRowKeys: true,
    onChange: (keys) => {
      const jobIds = keys.map(Number);
      if (jobIds.length > 500) {
        message.warning("一次最多选择 500 个岗位");
        return;
      }
      setSelectedJobIds(jobIds);
    },
    getCheckboxProps: () => ({ disabled: batchAction !== null }),
  };

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
            onClick={() => void toggleFavorite(job)}
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
            onClick={batchAction === null ? () => setDetailJob(job) : undefined}
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
            onClick={() => setDetailJob(job)}
          >
            详情
          </Button>
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => setGenerateJob(job)}
          >
            生成简历
          </Button>
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => setManualResumeJob(job)}
          >
            自行编写
          </Button>
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => navigate(`/resumes?job_id=${job.id}`)}
          >
            相关简历
          </Button>
          <Button
            type="link"
            size="small"
            disabled={batchAction !== null}
            onClick={() => {
              setEditingJob(job);
              setFormOpen(true);
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除该岗位？"
            disabled={batchAction !== null}
            onConfirm={() => void removeJob(job.id)}
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
    <div>
      <div style={{ marginBottom: 16 }}>
        <Space wrap className="jobs-filter-bar">
          <Input.Search
            className="jobs-search-input"
            placeholder="搜索职位 / 公司 / 城市 / 描述 / 备注"
            allowClear
            disabled={batchAction !== null}
            defaultValue={keyword}
            onSearch={(value) => {
              setKeyword(value);
              setPage(1);
            }}
          />
          <Select
            placeholder="类型"
            allowClear
            disabled={batchAction !== null}
            style={{ width: 110 }}
            value={jobType || undefined}
            onChange={(value) => {
              setJobType(value ?? "");
              setPage(1);
            }}
            options={JOB_TYPE_OPTIONS}
          />
          <Select
            placeholder="状态"
            allowClear
            disabled={batchAction !== null}
            style={{ width: 110 }}
            value={status || undefined}
            onChange={(value) => {
              setStatus(value ?? "");
              setPage(1);
            }}
            options={STATUS_OPTIONS}
          />
          {selectionMode ? (
            <Button
              icon={<CloseCircleOutlined />}
              disabled={batchAction !== null}
              onClick={exitSelectionMode}
            >
              退出选择
            </Button>
          ) : (
            <Button
              icon={<CheckSquareOutlined />}
              disabled={batchAction !== null}
              onClick={() => setSelectionMode(true)}
            >
              选择
            </Button>
          )}
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={batchAction !== null}
            onClick={() => setFormOpen(true)}
          >
            手动添加
          </Button>
        </Space>
      </div>

      {selectionMode && (
        <Space style={{ marginBottom: 12, minHeight: 32 }} wrap>
          <Typography.Text type="secondary">已选 {selectedJobIds.length} 个岗位</Typography.Text>
          <Button
            icon={<ClearOutlined />}
            disabled={selectedJobIds.length === 0 || batchAction !== null}
            onClick={() => {
              setSelectedJobIds([]);
              setBatchStatus(undefined);
            }}
          >
            清空选择
          </Button>
          <Select
            placeholder="批量设置状态"
            value={batchStatus}
            options={STATUS_OPTIONS}
            style={{ width: 150 }}
            disabled={selectedJobIds.length === 0 || batchAction !== null}
            onChange={setBatchStatus}
          />
          <Button
            icon={<CheckOutlined />}
            disabled={selectedJobIds.length === 0 || !batchStatus || batchAction !== null}
            loading={batchAction === "status"}
            onClick={() => void applyBatchStatus()}
          >
            应用状态
          </Button>
          <Popconfirm
            title={`确定删除选中的 ${selectedJobIds.length} 个岗位？`}
            description="删除后无法恢复"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            disabled={selectedJobIds.length === 0 || batchAction !== null}
            onConfirm={() => removeSelectedJobs()}
          >
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={selectedJobIds.length === 0 || batchAction !== null}
              loading={batchAction === "delete"}
            >
              批量删除
            </Button>
          </Popconfirm>
        </Space>
      )}

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
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
      />

      <JobDetailDrawer
        job={detailJob}
        onClose={() => setDetailJob(null)}
        onGenerate={(job) => setGenerateJob(job)}
        onWrite={(job) => setManualResumeJob(job)}
        onViewResumes={(job) => navigate(`/resumes?job_id=${job.id}`)}
        onAnalyze={setAnalysisJob}
        onAskAssistant={(job) => navigate(`/assistant?job_id=${job.id}`)}
        onFavorite={(job) => void toggleFavorite(job)}
        favoriteLoading={favoriteJobId === detailJob?.id}
      />
      <JobFormModal
        open={formOpen}
        initial={editingJob}
        onClose={() => {
          setFormOpen(false);
          setEditingJob(null);
        }}
        onSaved={() => void reload()}
      />
      <GenerateResumeModal job={generateJob} onClose={() => setGenerateJob(null)} />
      <ManualResumeModal job={manualResumeJob} onClose={() => setManualResumeJob(null)} />
      <JobAnalysisModal job={analysisJob} onClose={() => setAnalysisJob(null)} />
    </div>
  );
}
