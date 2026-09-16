/** 岗位广场：搜索筛选、手动添加、详情与生成简历入口。 */
import {
  CheckSquareOutlined,
  CheckOutlined,
  ClearOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  InboxOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { App, Button, Input, Popconfirm, Select, Space, Typography } from "antd";
import type { TableRowSelection } from "antd/es/table/interface";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { markCandidateJobImported } from "../api/candidateJob";
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
import CandidateJobsDrawer from "../components/jobs/CandidateJobsDrawer";
import JobTable from "../components/jobs/JobTable";
import { useApi } from "../hooks/useApi";
import type { CandidateJob, Job } from "../types";

const JOB_TYPE_OPTIONS = ["校招", "实习", "社招", "其他"].map((value) => ({ value, label: value }));
const STATUS_OPTIONS = ["开放中", "已截止", "已投递"].map((value) => ({ value, label: value }));
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
  // 备选岗位：抽屉里暂存未核对的招聘信息，导入时走正式岗位表单。
  const [candidatesOpen, setCandidatesOpen] = useState(false);
  const [importCandidate, setImportCandidate] = useState<CandidateJob | null>(null);
  const [importedCandidateId, setImportedCandidateId] = useState<number | null>(null);
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
            icon={<InboxOutlined />}
            disabled={batchAction !== null}
            onClick={() => setCandidatesOpen(true)}
          >
            备选岗位
          </Button>
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

      <JobTable
        jobs={jobs}
        loading={loading}
        selectionMode={selectionMode}
        rowSelection={rowSelection}
        batchAction={batchAction}
        favoriteJobId={favoriteJobId}
        page={page}
        pageSize={pageSize}
        onToggleFavorite={(job) => void toggleFavorite(job)}
        onOpenDetail={setDetailJob}
        onGenerate={setGenerateJob}
        onWrite={setManualResumeJob}
        onViewResumes={(job) => navigate("/resumes?job_id=" + job.id)}
        onEdit={(job) => {
          setEditingJob(job);
          setFormOpen(true);
        }}
        onDelete={(job) => void removeJob(job.id)}
        onPageChange={(nextPage, nextPageSize) => {
          setPage(nextPage);
          setPageSize(nextPageSize);
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
        // 从备选岗位导入时，把原文预填进表单并标注来源。
        presetRawText={importCandidate?.raw_text ?? ""}
        presetSource={importCandidate ? "备选岗位导入" : undefined}
        onClose={() => {
          setFormOpen(false);
          setEditingJob(null);
          setImportCandidate(null);
        }}
        onSaved={(jobId) => {
          void reload();
          const candidate = importCandidate;
          if (!candidate || !jobId) return;
          setImportCandidate(null);
          setImportedCandidateId(candidate.id);
          void markCandidateJobImported(candidate.id, jobId)
            .then(() => message.success("备选岗位已导入正式岗位"))
            .catch((err) => message.error(err instanceof Error ? err.message : "标记导入状态失败"));
        }}
      />
      <CandidateJobsDrawer
        open={candidatesOpen}
        importedCandidateId={importedCandidateId}
        onClose={() => setCandidatesOpen(false)}
        onImport={(candidate) => {
          setImportCandidate(candidate);
          setEditingJob(null);
          setFormOpen(true);
          setCandidatesOpen(false);
        }}
      />
      <GenerateResumeModal
        job={generateJob}
        open={!!generateJob}
        onClose={() => setGenerateJob(null)}
      />
      <ManualResumeModal
        job={manualResumeJob}
        open={!!manualResumeJob}
        onClose={() => setManualResumeJob(null)}
      />
      <JobAnalysisModal job={analysisJob} onClose={() => setAnalysisJob(null)} />
    </div>
  );
}
