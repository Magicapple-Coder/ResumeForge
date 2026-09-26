/** 岗位广场：搜索筛选、手动添加、详情与生成简历入口。 */
import {
  CheckSquareOutlined,
  CheckOutlined,
  ClearOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { App, Button, Input, Popconfirm, Select, Space, Typography } from "antd";
import type { TableRowSelection } from "antd/es/table/interface";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { markCandidateJobImported } from "../api/candidateJob";
import { addToQueue, QueueConflictError, startBackfill } from "../api/apply";
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
import JobMatchModal from "../components/JobMatchModal";
import ManualResumeModal from "../components/ManualResumeModal";
import { candidateImportSource } from "../utils/jobSource";
import CandidateJobsDrawer, { candidateToJobPayload } from "../components/jobs/CandidateJobsDrawer";
import JobTable from "../components/jobs/JobTable";
import { useApi } from "../hooks/useApi";
import type { CandidateJobDetail, Job } from "../types";

const JOB_TYPE_OPTIONS = ["校招", "实习", "社招", "其他"].map((value) => ({ value, label: value }));
const STATUS_OPTIONS = ["开放中", "已截止", "已投递"].map((value) => ({ value, label: value }));
// 与后端 `source_kind` 查询参数一一对应；标签用「自动采集 / 手动添加」是因为这是用户能
// 一眼理解的二分，而不是把 recognition_source 的原始值直接搬上来。
const SOURCE_KIND_OPTIONS = [
  { value: "collected", label: "自动采集" },
  { value: "manual", label: "手动添加" },
];
type BatchAction = "status" | "delete" | null;

export default function JobsPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { message, modal } = App.useApp();

  const [keyword, setKeyword] = useState(searchParams.get("keyword") ?? "");
  const [jobType, setJobType] = useState("");
  const [status, setStatus] = useState("");
  const [sourceKind, setSourceKind] = useState<"" | "collected" | "manual">("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [detailJob, setDetailJob] = useState<Job | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<Job | null>(null);
  const [generateJob, setGenerateJob] = useState<Job | null>(null);
  const [manualResumeJob, setManualResumeJob] = useState<Job | null>(null);
  const [analysisJob, setAnalysisJob] = useState<Job | null>(null);
  const [matchJob, setMatchJob] = useState<Job | null>(null);
  const [queueJobId, setQueueJobId] = useState<number | null>(null);
  const [selectedJobIds, setSelectedJobIds] = useState<number[]>([]);
  const [batchStatus, setBatchStatus] = useState<string>();
  const [batchAction, setBatchAction] = useState<BatchAction>(null);
  const [favoriteJobId, setFavoriteJobId] = useState<number | null>(null);
  // 「补齐详情」触发中：防止连点，也让按钮有个加载态。
  const [backfilling, setBackfilling] = useState(false);
  // 备选岗位：抽屉里暂存未核对的招聘信息，导入时走正式岗位表单。
  const [candidatesOpen, setCandidatesOpen] = useState(false);
  // 导入用**详情**那一份：列表不带 JD，用它预填表单会得到一个没有职位描述的空表单。
  const [importCandidate, setImportCandidate] = useState<CandidateJobDetail | null>(null);
  const [importedCandidateId, setImportedCandidateId] = useState<number | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const linkedJobId = Number(searchParams.get("job_id")) || null;
  const collectTaskIdsKey = searchParams.get("collect_task_ids") ?? "";
  const collectTaskIds = useMemo(
    () => [
      ...new Set(
        collectTaskIdsKey
          .split(",")
          .map(Number)
          .filter((value) => Number.isInteger(value) && value > 0),
      ),
    ],
    [collectTaskIdsKey],
  );
  const [openedCollectTaskIdsKey, setOpenedCollectTaskIdsKey] = useState("");
  const [openedLinkedJobId, setOpenedLinkedJobId] = useState<number | null>(null);

  const {
    data: jobs,
    loading,
    reload,
    error,
  } = useApi(
    () =>
      listJobs({
        keyword,
        job_type: jobType,
        status,
        source_kind: sourceKind || undefined,
        page,
        page_size: pageSize,
      }),
    [keyword, jobType, status, sourceKind, page, pageSize],
  );

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  useEffect(() => {
    if (!collectTaskIdsKey || openedCollectTaskIdsKey === collectTaskIdsKey) return;
    setCandidatesOpen(true);
    setOpenedCollectTaskIdsKey(collectTaskIdsKey);
  }, [collectTaskIdsKey, openedCollectTaskIdsKey]);

  // 只有"职位描述为空"的岗位才值得补详情（补详情要逐个打开页面，很慢），按钮据此出现/消失，
  // 而不是常驻一个点了没反应的按钮。当前只统计这一页已加载的岗位：补的就这一页里空的那些。
  const emptyDescriptionJobIds = (jobs?.items ?? [])
    .filter((job) => !job.description.trim())
    .map((job) => job.id);

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
        message.success("已移入回收站，可在「回收站」里恢复");
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

  const addJobToQueue = useCallback(
    async (job: Job, confirm: { unanalyzed?: boolean; realGap?: boolean } = {}) => {
      setQueueJobId(job.id);
      try {
        await addToQueue([
          {
            job_id: job.id,
            confirm_unanalyzed: confirm.unanalyzed,
            confirm_real_gap: confirm.realGap,
          },
        ]);
        message.success("已加入投递台队列");
      } catch (err) {
        if (err instanceof QueueConflictError) {
          const detail = err.detail;
          if (detail.site_unsupported) {
            // 这一类**没有"仍然加入"的选项**：确认也放行不了（投递时定位不到站点），
            // 所以只给一个必须点掉的提示，而不是给个按钮让人以为可以强行通过。
            modal.warning({
              title: "这个岗位不能自动投递",
              content: detail.message,
              okText: "知道了",
            });
          } else if (detail.unanalyzed) {
            modal.confirm({
              title: "该岗位还没做过匹配分析",
              content: "建议先做「匹配度分析」。也可以直接加入队列，投递前仍会再核对一次。",
              okText: "仍然加入队列",
              cancelText: "取消",
              onOk: () => addJobToQueue(job, { unanalyzed: true }),
            });
          } else if (detail.gaps && detail.gaps.length > 0) {
            modal.confirm({
              title: "该岗位存在真实缺口，默认不投",
              content: `匹配分析判定你确实不具备这些要求：${detail.gaps.join("、")}。确认仍要投递该岗位吗？`,
              okText: "确认仍然投递",
              okButtonProps: { danger: true },
              cancelText: "取消",
              onOk: () => addJobToQueue(job, { realGap: true }),
            });
          } else {
            message.warning(detail.message);
          }
        } else {
          message.error(err instanceof Error ? err.message : "加入投递台失败");
        }
      } finally {
        setQueueJobId(null);
      }
    },
    [message, modal],
  );

  const backfillDetails = async () => {
    // 批量优先：选择模式下有勾选就补勾选的，否则补当前这页所有 JD 为空的岗位。
    const target =
      selectionMode && selectedJobIds.length > 0 ? selectedJobIds : emptyDescriptionJobIds;
    if (target.length === 0) {
      message.warning("当前页没有需要补齐详情的岗位");
      return;
    }
    setBackfilling(true);
    try {
      await startBackfill(target);
      // 它是 kind=collect 的批次，界面入口在投递台：不告诉用户去哪儿看，他会以为点了没反应。
      message.success(`已开始为 ${target.length} 个岗位补齐详情，进度见「投递台 → 自动采集」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "补齐详情失败");
    } finally {
      setBackfilling(false);
    }
  };

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
          <Select
            aria-label="来源筛选"
            placeholder="来源"
            allowClear
            disabled={batchAction !== null}
            style={{ width: 120 }}
            value={sourceKind || undefined}
            onChange={(value) => {
              setSourceKind((value ?? "") as "" | "collected" | "manual");
              setPage(1);
            }}
            options={SOURCE_KIND_OPTIONS}
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
          {emptyDescriptionJobIds.length > 0 && (
            // 只在有 JD 为空的岗位时才出现——否则按钮点了什么也不会发生。
            // 显式 aria-label：antd 会给纯中文按钮做字距处理，用文本当查询条件可能找不到。
            <Button
              icon={<ReloadOutlined />}
              aria-label="补齐详情"
              disabled={batchAction !== null}
              loading={backfilling}
              onClick={() => void backfillDetails()}
            >
              补齐详情
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
        onMatch={setMatchJob}
        onAddToQueue={(job) => void addJobToQueue(job)}
        onAskAssistant={(job) => navigate(`/assistant?job_id=${job.id}`)}
        onFavorite={(job) => void toggleFavorite(job)}
        favoriteLoading={favoriteJobId === detailJob?.id}
        queueLoading={queueJobId === detailJob?.id}
      />
      <JobFormModal
        open={formOpen}
        initial={editingJob}
        // 从备选岗位导入时，把原文预填进表单并标注来源。
        presetRawText={importCandidate?.raw_text ?? ""}
        // 采集来的候选没有 raw_text，内容在结构化字段里——只给原文那一路会让表单整个空着。
        presetJob={importCandidate ? candidateToJobPayload(importCandidate) : undefined}
        // 来源要**继承候选自己的来路**：写死「备选岗位导入」会让采集回来的岗位在列表里
        // 挂上「手动」角标（用户明明是从投递台采集回来的）。
        presetSource={importCandidate ? candidateImportSource(importCandidate) : undefined}
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
        collectTaskIds={collectTaskIds}
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
      <JobMatchModal job={matchJob} onClose={() => setMatchJob(null)} />
    </div>
  );
}
