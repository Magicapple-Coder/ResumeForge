/**
 * 官网采集：从公司自己的招聘官网取岗位，并给出"这次到底抓全了没有"的凭据。
 *
 * 这个页面的重点不是"抓到了多少条"，而是**对账结论与它的依据**。所以采集结果一律以
 * 「三态结论 + 一句话理由 + 可展开的逐层依据」呈现，而不是一个成功提示或一个百分比。
 */
import { PlusOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Input, InputNumber, Space, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  collectOfficialSite,
  createOfficialSite,
  deleteOfficialSite,
  getOfficialRun,
  listOfficialRuns,
  listOfficialSites,
  reprobeOfficialSite,
  stopOfficialRun,
  updateOfficialSite,
  verifyOfficialRun,
} from "../api/official";
import type {
  OfficialProbeResult,
  OfficialRun,
  OfficialRunDetail,
  OfficialSite,
  OfficialSitePayload,
} from "../types";
import OfficialBetaNoticeModal from "../components/official/OfficialBetaNoticeModal";
import OfficialBrowserBar from "../components/official/OfficialBrowserBar";
import OfficialRunReportDrawer from "../components/official/OfficialRunReportDrawer";
import OfficialRunHistoryTable from "../components/official/OfficialRunHistoryTable";
import OfficialSiteEditorModal from "../components/official/OfficialSiteEditorModal";
import OfficialSiteTable from "../components/official/OfficialSiteTable";
import { consumeOfficialBetaNotice } from "../utils/officialBetaNotice";

const { Text } = Typography;

/**
 * 「本次最多抓多少条」的上限，与后端 ``CollectRequest.max_jobs`` 的 ``le`` 取同一个值。
 *
 * **两边必须一致**：界面限死是为了让用户当场看到边界，后端限死是因为界面不是守门人
 * （手改请求、旧版界面都绕得过去）。只做一边的后果是"填了 5000、提交后弹一句校验错误"。
 */
const MAX_JOBS_LIMIT = 2000;

/**
 * 采集记录一次列这么多条。
 *
 * 采过一次就留一条，日积月累会有几百条；而这一栏的用途是"回看最近采过什么"，
 * 不是归档。给一个够用的窗口，比无限长（越翻越慢）或分页（多一层交互）都更贴用途。
 */
const RUN_HISTORY_LIMIT = 20;

/**
 * 只有"摘要"时的报告抽屉占位。
 *
 * 点采集后接口**立刻**返回一条运行记录（列表形状，没有逐层依据），抽屉要先开起来给用户看
 * 进展，完整的报告随后再取。这份占位就是那个中间态。
 *
 * 类型写成 `Omit<OfficialRunDetail, keyof OfficialRun>`（也就是"Detail 比 Run 多出来的
 * 那几项"），**为的是在 Detail 新增必填字段时这里直接编译不过**——不加这个约束的话，
 * 新字段会被悄悄漏掉，而界面读到 `undefined` 才炸，正是这个文件上一版的 bug。
 */
const RUN_DETAIL_PLACEHOLDER: Omit<OfficialRunDetail, keyof OfficialRun> = {
  reconcile_detail: {},
  // 一条都还没读出来，所以是合法的空值，不是"未知"。
  extraction: { methods: [], llm_calls: 0, recipes_learned: 0, deep_links_skipped: 0 },
};

/** robots 列：三态（未查/允许/不允许）。 */
export default function OfficialPage() {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [sites, setSites] = useState<OfficialSite[]>([]);
  // 采集记录（跨公司，按时间倒序）。**采集是个"跑完就看不见过程"的动作**：没有这份记录，
  // 第二天就不知道上次采的是哪家、采到什么程度、为什么停下来。
  const [runs, setRuns] = useState<OfficialRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [busySiteIds, setBusySiteIds] = useState<number[]>([]);
  // 本次采集的条数上限（空 = 不设）。**留在组件状态里而不是每次重填**：用户设了 20 条之后
  // 多半还要接着看下一家公司，每采一次就清空等于逼他重打一遍。
  const [maxJobs, setMaxJobs] = useState<number | undefined>(undefined);
  const [jobKeywords, setJobKeywords] = useState("");
  const [selectedSiteIds, setSelectedSiteIds] = useState<number[]>([]);
  const [betaNoticeOpen, setBetaNoticeOpen] = useState(false);
  const [report, setReport] = useState<OfficialRunDetail | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [probeNotice, setProbeNotice] = useState<OfficialProbeResult | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [editingSite, setEditingSite] = useState<OfficialSite | null>(null);
  const [selectedRunIds, setSelectedRunIds] = useState<number[]>([]);
  const [runBatchAction, setRunBatchAction] = useState<"stop" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 两份一起取：它们是同一屏上的两块，分两次渲染会先闪一下空的采集记录。
      const [nextSites, nextRuns] = await Promise.all([
        listOfficialSites(),
        listOfficialRuns({ limit: RUN_HISTORY_LIMIT }),
      ]);
      setSites(nextSites);
      setRuns(nextRuns);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载官网源失败");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  // 首次进这个页面自动弹一次能力边界说明（一个浏览器一次）。
  // `consumeOfficialBetaNotice` 是"读并写"的原子操作：StrictMode 下 effect 会跑两次，
  // 分成两次判断会弹两遍。
  useEffect(() => {
    // 页面上已经有别的弹窗（典型是首次使用引导——它会带着用户一页页走，可能正好停在这一页）
    // 就先不弹：两层弹窗叠在一起，用户不知道该看哪个。
    //
    // 这里用 DOM 而不是状态来判断"引导开着没有"，是因为引导的状态在 App 层、本页拿不到；
    // 而"此时屏幕上有没有弹窗"本来就是一个展示层的问题，用展示层的事实判断反而更准。
    // 代价：用户在别处开着任意弹窗时进来这一页，这个提示会推迟到下次访问——
    // 顶部那条常驻提示一直在，不会漏掉信息。
    if (document.querySelector(".ant-modal-root")) return;
    if (consumeOfficialBetaNotice()) setBetaNoticeOpen(true);
  }, []);

  /**
   * 探测结果的三态提示。
   *
   * **"被阻断"与"未识别"必须分开说**：前者是"我们没看到内容"，后者是"这家公司不用这套系统"。
   * 混成一句"识别失败"，用户会去删掉一个其实能用的源。
   */
  const showProbeNotice = useCallback(
    (result: OfficialProbeResult) => {
      setProbeNotice(result);
      if (result.state === "hit") {
        message.success(`已识别：${result.site.source_label}`);
      } else if (result.state === "blocked") {
        message.warning("探测被站点阻断，暂时无法判断这家公司用哪套招聘系统");
      } else {
        message.info("没有识别出已知的招聘系统");
      }
    },
    [message],
  );

  const handleCreate = async (values: OfficialSitePayload) => {
    setSubmitting(true);
    try {
      const result = await createOfficialSite(values);
      setFormOpen(false);
      showProbeNotice(result);
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "添加失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = async (values: OfficialSitePayload) => {
    if (!editingSite) return;
    setSubmitting(true);
    try {
      const result = await updateOfficialSite(editingSite.id, values);
      setEditingSite(null);
      showProbeNotice(result);
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存公司信息失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleProbe = async (site: OfficialSite) => {
    setBusySiteIds([site.id]);
    try {
      showProbeNotice(await reprobeOfficialSite(site.id));
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重新探测失败");
    } finally {
      setBusySiteIds([]);
    }
  };

  const handleCollect = async (site: OfficialSite) => {
    setBusySiteIds([site.id]);
    try {
      // **接口立刻返回**，实际采集在后台跑——多页站点是几十次请求加限速等待，
      // 同步等它会把界面挂住。所以先拿列表里那条运行记录把抽屉打开，再去取完整报告。
      const run = jobKeywords.trim()
        ? await collectOfficialSite(site.id, maxJobs, jobKeywords.trim())
        : await collectOfficialSite(site.id, maxJobs);
      // **不要用 `as` 把它硬转成 Detail。** 这里曾经写的是
      // `{ ...run, reconcile_detail: {} } as OfficialRunDetail`，类型检查因此对
      // "Detail 新增了必填字段"完全无感——`extraction` 就是这样漏进来的：报告抽屉一打开
      // 就去读 `report.extraction.methods`，读到 undefined，整页白屏。
      // 现在占位对象有明确类型，**Detail 上再加必填字段会在这里编译不过**。
      setReport({ ...run, ...RUN_DETAIL_PLACEHOLDER });
      await load();
      if (run.status === "running") {
        // 还在跑：由下面的轮询去补完整报告（含结论与逐层依据）。
        return;
      }
      // 已经结束了（例如被 robots 拒绝，那是当场就有结论的）：直接取完整报告，
      // 否则抽屉里会缺掉结论与依据——而依据才是这个功能的产物。
      await openReport(run.id);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "采集失败");
    } finally {
      setBusySiteIds([]);
    }
  };

  const handleBatchCollect = async () => {
    const targets = sites.filter(
      (site) =>
        selectedSiteIds.includes(site.id) && site.can_collect && site.latest_status !== "running",
    );
    if (targets.length === 0) {
      message.warning("请先选择可以采集的公司");
      return;
    }
    setBusySiteIds(targets.map((site) => site.id));
    try {
      const results = await Promise.allSettled(
        targets.map((site) =>
          jobKeywords.trim()
            ? collectOfficialSite(site.id, maxJobs, jobKeywords.trim())
            : collectOfficialSite(site.id, maxJobs),
        ),
      );
      const successful = results.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : [],
      );
      const failures = results.filter((result) => result.status === "rejected");
      setSelectedSiteIds([]);
      await load();
      if (successful.length > 0) await openReport(successful[0].id);
      if (failures.length > 0) {
        message.warning(`${successful.length} 家已开始采集，${failures.length} 家启动失败`);
      } else {
        message.success(`已同时开始 ${successful.length} 家公司的采集`);
      }
    } finally {
      setBusySiteIds([]);
    }
  };

  const handleStop = async () => {
    if (!report) return;
    setStopping(true);
    try {
      await stopOfficialRun(report.id);
      message.info("已请求停止，采集会在当前这一条岗位之后收尾");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "停止失败");
    } finally {
      setStopping(false);
    }
  };

  /** 采集中：定时把报告刷新出来，跑完再刷一次列表。 */
  useEffect(() => {
    if (report?.status !== "running") return;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const updated = await getOfficialRun(report.id);
          setReport(updated);
          if (updated.status !== "running") await load();
        } catch {
          // 轮询失败不打断：下一轮再来。这里弹错误只会在采集期间刷屏。
        }
      })();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [report?.id, report?.status, load]);

  const openReport = useCallback(
    async (runId: number) => {
      setReportLoading(true);
      try {
        setReport(await getOfficialRun(runId));
      } catch (error) {
        message.error(error instanceof Error ? error.message : "加载采集报告失败");
      } finally {
        setReportLoading(false);
      }
    },
    [message],
  );

  const handleDelete = (site: OfficialSite) => {
    modal.confirm({
      title: `删除「${site.company}」？`,
      content: "这家公司的采集记录与计数趋势会一并删除，已采集到暂存区的岗位不受影响。",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await deleteOfficialSite(site.id);
          await load();
        } catch (error) {
          message.error(error instanceof Error ? error.message : "删除失败");
        }
      },
    });
  };

  /** 核实待核实地址并按新结论刷新报告。 */
  const handleVerify = async () => {
    if (!report) return;
    setVerifying(true);
    try {
      const updated = await verifyOfficialRun(report.id);
      setReport(updated);
      message.info(updated.headline || "核实完成");
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "核实失败");
    } finally {
      setVerifying(false);
    }
  };

  const openCandidates = (runIds: number[]) => {
    const uniqueIds = [...new Set(runIds)].filter((id) => Number.isFinite(id));
    if (uniqueIds.length === 0) return;
    navigate(`/jobs?collect_task_ids=${uniqueIds.join(",")}`);
  };

  const handleBatchStopRuns = async () => {
    const targets = runs.filter(
      (run) => selectedRunIds.includes(run.id) && run.status === "running",
    );
    if (targets.length === 0) {
      message.warning("选中的记录里没有正在采集的任务");
      return;
    }
    setRunBatchAction("stop");
    try {
      const results = await Promise.allSettled(targets.map((run) => stopOfficialRun(run.id)));
      const failed = results.filter((result) => result.status === "rejected").length;
      setSelectedRunIds([]);
      await load();
      if (failed > 0) message.warning(`${targets.length - failed} 条已请求停止，${failed} 条失败`);
      else message.success(`已请求停止 ${targets.length} 条采集`);
    } finally {
      setRunBatchAction(null);
    }
  };

  return (
    <div>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Card>
          <Space direction="vertical" size={4} style={{ width: "100%" }}>
            <Space style={{ width: "100%", justifyContent: "space-between" }}>
              <Text strong style={{ fontSize: 16 }}>
                官网采集
              </Text>
              <Space>
                <Button
                  disabled={selectedSiteIds.length === 0 || busySiteIds.length > 0}
                  onClick={() => void handleBatchCollect()}
                >
                  批量采集{selectedSiteIds.length > 0 ? `（${selectedSiteIds.length}）` : ""}
                </Button>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setFormOpen(true)}>
                  添加公司
                </Button>
              </Space>
            </Space>
            <Text type="secondary">
              填入公司官网或招聘页地址，应用会识别它背后的招聘系统并直接读取岗位，
              然后给出「这次抓全了没有」的凭据。采集结果先进入备选岗位，核对后再导入岗位广场。
            </Text>
            {/* 常驻的能力边界说明。弹窗只自动弹一次（见 officialBetaNotice），漏看的人
                每次进页面还能看到这一条——"读不出来是我的问题吗"必须随时有答案。 */}
            <Alert
              type="warning"
              showIcon
              message={
                <Space size={6} wrap>
                  <span>
                    这个模块还不完善，会在后续版本逐步修复与扩充；「无法确认」不等于这家公司没有岗位。
                  </span>
                  <Button type="link" size="small" onClick={() => setBetaNoticeOpen(true)}>
                    看详细说明
                  </Button>
                </Space>
              }
            />
            <Space size={6} wrap>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                本次最多抓
              </Typography.Text>
              <InputNumber
                size="small"
                min={1}
                max={MAX_JOBS_LIMIT}
                style={{ width: 96 }}
                placeholder="不设"
                value={maxJobs}
                onChange={(value) => setMaxJobs(value ?? undefined)}
                aria-label="本次最多抓多少条"
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                条（留空则不设上限）。<strong>只对这一次生效</strong>
                ，不记住——岗位上万条的站点一次翻不完，填它就不用干等十几分钟再手动停。
              </Typography.Text>
            </Space>
            <Space size={6} wrap>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                本次只采集岗位
              </Typography.Text>
              <Input
                size="small"
                value={jobKeywords}
                onChange={(event) => setJobKeywords(event.target.value)}
                placeholder="如：Java、后端工程师、上海"
                aria-label="本次岗位关键词"
                style={{ width: 260 }}
                maxLength={200}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                可用顿号、逗号或换行分隔；会继续翻页寻找匹配岗位
              </Typography.Text>
            </Space>
            <OfficialBrowserBar />
          </Space>
        </Card>

        {probeNotice && probeNotice.state !== "hit" && (
          <Alert
            type={probeNotice.state === "blocked" ? "warning" : "info"}
            showIcon
            closable
            onClose={() => setProbeNotice(null)}
            message={probeNotice.state_label}
            description={
              <Space direction="vertical" size={2}>
                <Text>{probeNotice.evidence}</Text>
                {probeNotice.attempts.length > 0 && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    尝试过 {probeNotice.attempts.length} 个地址，
                    {probeNotice.attempts
                      .map((item) => `${item.endpoint}（${item.block_label}）`)
                      .join("；")}
                  </Text>
                )}
                {/* "没试完"那句话由后端写进 evidence——同一句只该有一处，而它还会落进源的
                    「判断依据」里长期展示；这里再渲染一遍就是同一句话说两次。 */}
              </Space>
            }
          />
        )}

        <Card>
          <OfficialSiteTable
            sites={sites}
            loading={loading}
            busySiteIds={busySiteIds}
            submitting={submitting}
            selectedSiteIds={selectedSiteIds}
            onSelectedSiteIdsChange={setSelectedSiteIds}
            onEdit={setEditingSite}
            onCollect={(site) => void handleCollect(site)}
            onProbe={(site) => void handleProbe(site)}
            onDelete={handleDelete}
            onOpenReport={(runId) => void openReport(runId)}
          />
        </Card>

        {/*
          采集记录：**采集是个"跑完就看不见过程"的动作**。没有这一栏，第二天就不知道上次采的是
          哪家、采到什么程度、为什么停下来；而"为什么停下来"恰恰是这个功能最要紧的信息之一
          （页数上限？你设的条数？站点阻断？）。
          跨公司、按时间倒序——用户问的是"我最近采过些什么"，不是"这家公司采过几次"。
        */}
        <Card title="采集记录" size="small">
          <OfficialRunHistoryTable
            runs={runs}
            loading={loading}
            selectedRunIds={selectedRunIds}
            batchAction={runBatchAction}
            onSelectedRunIdsChange={setSelectedRunIds}
            onBatchStop={() => void handleBatchStopRuns()}
            onOpenCandidates={openCandidates}
            onOpenReport={(runId) => void openReport(runId)}
          />
        </Card>
      </Space>

      <OfficialBetaNoticeModal open={betaNoticeOpen} onClose={() => setBetaNoticeOpen(false)} />
      <OfficialSiteEditorModal
        open={formOpen}
        site={null}
        submitting={submitting}
        onCancel={() => setFormOpen(false)}
        onSubmit={handleCreate}
      />
      <OfficialSiteEditorModal
        open={editingSite !== null}
        site={editingSite}
        submitting={submitting}
        onCancel={() => setEditingSite(null)}
        onSubmit={handleEdit}
      />
      <OfficialRunReportDrawer
        report={report}
        reportLoading={reportLoading}
        stopping={stopping}
        verifying={verifying}
        onClose={() => setReport(null)}
        onStop={handleStop}
        onVerify={handleVerify}
        onOpenCandidates={(runId) => openCandidates([runId])}
      />
    </div>
  );
}
