/**
 * 面试深挖：针对台账里每一条主张做压力测试，结束时给一份"该去补什么"的清单。
 *
 * 与「模拟面试」的分工写在页面上：那边按轮数推进、给四维度评分；这边**不评总分**，
 * 用证据状态回答"这条主张我到底讲不讲得清"。所以界面上也不该出现任何分数。
 *
 * 两个刻意的呈现选择：
 * - **反馈策略默认「真实模拟」**：每题后不念判定，因为念了会让人按判分标准答题，
 *   而不像真面试。判定仍如实回传（界面不撒谎），只是不主动展示。
 * - **评分契约在整个会话期间可见**：它是"判定标准"，用户有权看到自己在被怎么衡量——
 *   藏起来才会让人怀疑"是不是看人下菜碟"。
 */
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Statistic,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  CheckCircleOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  answerDrill,
  createDrillSession,
  deleteDrillSession,
  finishDrill,
  getDrillSession,
  listDrillSessions,
  listRehearsal,
  rehearse,
} from "../api/drill";
import { listClaims } from "../api/claims";
import { listJobs } from "../api/jobs";
import { useApi } from "../hooks/useApi";
import type {
  Claim,
  DrillRehearsalRow,
  DrillSession,
  DrillSessionBrief,
  EvidenceStatus,
  FeedbackPolicy,
} from "../types";
import {
  ACTION_KIND_HINTS,
  DRILL_QUESTION_OPTIONS,
  EVIDENCE_COLORS,
  EVIDENCE_HINTS,
  EVIDENCE_LABELS,
  FEEDBACK_LABELS,
  FOLLOWUP_LABELS,
  REHEARSE_LABELS,
} from "../types";

function evidenceTag(status: EvidenceStatus) {
  return (
    <Tooltip key={status} title={EVIDENCE_HINTS[status]}>
      <Tag color={EVIDENCE_COLORS[status]}>{EVIDENCE_LABELS[status]}</Tag>
    </Tooltip>
  );
}

/** 开场面板：选主张、定题数与反馈方式。 */
function StartPanel({ onStarted }: { onStarted: (session: DrillSession) => void }) {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [claimIds, setClaimIds] = useState<number[]>([]);
  const [jobId, setJobId] = useState<number | null>(null);
  const [maxQuestions, setMaxQuestions] = useState(6);
  const [policy, setPolicy] = useState<FeedbackPolicy>("deferred");
  const [jobOptions, setJobOptions] = useState<{ value: number; label: string }[]>([]);
  const [busy, setBusy] = useState(false);

  // 只有「已确认」的主张能挖——待确认的本来就还没定稿。
  const claims = useApi<Claim[]>(
    () => listClaims({ status: "已确认" }).then((page) => page.items),
    [],
  );

  useEffect(() => {
    if (!open) return;
    void listJobs({ page: 1, page_size: 100 })
      .then((page) =>
        setJobOptions(
          page.items.map((job) => ({
            value: job.id,
            label: `${job.title}${job.company ? ` · ${job.company}` : ""}`,
          })),
        ),
      )
      .catch(() => setJobOptions([]));
  }, [open]);

  const available = claims.data ?? [];

  const start = async () => {
    setBusy(true);
    try {
      const session = await createDrillSession({
        claim_ids: claimIds,
        job_id: jobId,
        max_questions: maxQuestions,
        feedback_policy: policy,
      });
      message.success("评分标准已经定下来，开始吧");
      setOpen(false);
      onStarted(session);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "开场失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => setOpen(true)}>
        开始深挖
      </Button>
      <Modal
        open={open}
        title="按台账深挖：先定标准，再提问"
        width={640}
        onCancel={() => setOpen(false)}
        footer={
          <Space>
            <Button onClick={() => setOpen(false)}>取消</Button>
            <Button type="primary" loading={busy} onClick={() => void start()}>
              开始
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="每道题的评分标准会在你看到问题**之前**定下来，之后不因答得流利而放宽。"
            description="深挖不评总分——它回答的是「这条主张我讲不讲得清、哪里还站不住」。"
          />
          <div>
            <Typography.Text strong>要验证哪些主张</Typography.Text>
            <Typography.Text type="secondary">（留空表示全部已确认的）</Typography.Text>
            {claims.loading ? (
              <Skeleton active paragraph={{ rows: 2 }} />
            ) : available.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="台账里还没有「已确认」的条目。先去「事实台账」确认几条。"
              />
            ) : (
              <Select
                mode="multiple"
                allowClear
                style={{ width: "100%", marginTop: 6 }}
                placeholder="全部已确认的主张"
                value={claimIds}
                onChange={setClaimIds}
                options={available.map((claim) => ({
                  value: claim.id,
                  label: `${claim.title || claim.subject}（${claim.responsibility_level}）`,
                }))}
              />
            )}
          </div>
          <Space size={12} wrap>
            <div>
              <Typography.Text strong>最多几道题</Typography.Text>
              <Select
                style={{ width: 120, marginLeft: 8 }}
                value={maxQuestions}
                onChange={setMaxQuestions}
                options={DRILL_QUESTION_OPTIONS.map((value) => ({ value, label: `${value} 道` }))}
              />
            </div>
            <div>
              <Typography.Text strong>反馈方式</Typography.Text>
              <Select
                style={{ width: 240, marginLeft: 8 }}
                value={policy}
                onChange={setPolicy}
                options={(["deferred", "immediate"] as FeedbackPolicy[]).map((value) => ({
                  value,
                  label: FEEDBACK_LABELS[value],
                }))}
              />
            </div>
          </Space>
          <div>
            <Typography.Text strong>关联岗位</Typography.Text>
            <Typography.Text type="secondary">（可选，用来挑更贴近岗位的问题）</Typography.Text>
            <Select
              allowClear
              style={{ width: "100%", marginTop: 6 }}
              placeholder="不关联"
              value={jobId}
              onChange={setJobId}
              options={jobOptions}
            />
          </div>
        </Space>
      </Modal>
    </>
  );
}

/** 复练队列：点一条就换一个角度出新题。 */
function RehearsalPanel({ sessionId }: { sessionId: number }) {
  const { message } = App.useApp();
  const [rows, setRows] = useState<DrillRehearsalRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<{ question: string; expect: string; label: string } | null>(
    null,
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listRehearsal(sessionId));
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (row: DrillRehearsalRow) => {
    setBusy(`${row.claim_title}-${row.kind}`);
    try {
      const fresh = await rehearse(sessionId, row);
      setResult({ question: fresh.question, expect: fresh.expect, label: fresh.claim_title });
    } catch (error) {
      message.error(error instanceof Error ? error.message : "出题失败");
    } finally {
      setBusy("");
    }
  };

  if (loading) return <Skeleton active paragraph={{ rows: 2 }} />;
  if (rows.length === 0) {
    return (
      <Typography.Text type="secondary">复练队列是空的——这一场没有需要再练的主张。</Typography.Text>
    );
  }

  return (
    <>
      <Typography.Paragraph type="secondary">
        复练不重复原题，换一个角度再问一次——把上次的答案背一遍不算会了。
      </Typography.Paragraph>
      <List
        size="small"
        dataSource={rows}
        renderItem={(row) => (
          <List.Item
            actions={[
              <Button
                key="go"
                size="small"
                type="link"
                loading={busy === `${row.claim_title}-${row.kind}`}
                onClick={() => void run(row)}
              >
                出一道
              </Button>,
            ]}
          >
            <Space direction="vertical" size={2} style={{ width: "100%" }}>
              <Space size={6} wrap>
                <Typography.Text strong>{row.claim_title}</Typography.Text>
                <Tag>{row.kind_label || REHEARSE_LABELS[row.kind as never] || row.kind}</Tag>
              </Space>
              {row.why && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {row.why}
                </Typography.Text>
              )}
            </Space>
          </List.Item>
        )}
      />
      <Modal
        open={result !== null}
        title={`复练：${result?.label ?? ""}`}
        onCancel={() => setResult(null)}
        footer={<Button onClick={() => setResult(null)}>关掉</Button>}
        width={620}
      >
        <Typography.Paragraph strong>{result?.question}</Typography.Paragraph>
        {result?.expect && (
          <Typography.Text type="secondary">这道题要求：{result.expect}</Typography.Text>
        )}
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
          这里只是出题，不会计入这一场的记录——想认真练，可以拿这个问题自己讲一遍。
        </Typography.Paragraph>
      </Modal>
    </>
  );
}

/** 复盘：三段结论 + 行动清单 + 复练队列。 */
function ReviewPanel({ session }: { session: DrillSession }) {
  const review = session.review;
  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {review.covered && (
        <Typography.Paragraph style={{ marginBottom: 0 }}>{review.covered}</Typography.Paragraph>
      )}
      {review.verified_summary && (
        <Alert type="success" showIcon message="讲得清的" description={review.verified_summary} />
      )}
      {review.gaps_summary && (
        <Alert type="warning" showIcon message="还站不住的" description={review.gaps_summary} />
      )}

      {(review.actions?.length ?? 0) > 0 && (
        <div>
          <Typography.Text strong>面试前的行动清单</Typography.Text>
          <List
            size="small"
            dataSource={review.actions ?? []}
            renderItem={(item) => (
              <List.Item>
                <Space direction="vertical" size={2} style={{ width: "100%" }}>
                  <Space size={6} wrap>
                    <Tag
                      color={
                        item.kind === "降表述" ? "red" : item.kind === "补知识" ? "blue" : "gold"
                      }
                    >
                      {item.kind}
                    </Tag>
                    <Typography.Text strong>{item.claim_title}</Typography.Text>
                  </Space>
                  <Typography.Text>{item.detail}</Typography.Text>
                  {ACTION_KIND_HINTS[item.kind] && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {ACTION_KIND_HINTS[item.kind]}
                    </Typography.Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </div>
      )}

      <div>
        <Typography.Text strong>复练队列</Typography.Text>
        <RehearsalPanel sessionId={session.id} />
      </div>
    </Space>
  );
}

/** 进行中的会话：当前这一问、契约、逐轮记录。 */
function ActiveSession({
  session,
  onUpdate,
}: {
  session: DrillSession;
  onUpdate: (session: DrillSession) => void;
}) {
  const { message } = App.useApp();
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastVerdict, setLastVerdict] = useState<{
    status: EvidenceStatus;
    missing: string[];
    contradictions: string[];
    feedback: string;
  } | null>(null);

  const pending = session.pending;
  const deferred = session.feedback_policy === "deferred";

  const submit = async () => {
    if (!answer.trim()) {
      message.warning("请先写下你的回答");
      return;
    }
    setBusy(true);
    try {
      const result = await answerDrill(session.id, answer.trim());
      setAnswer("");
      setLastVerdict({
        status: result.status,
        missing: result.missing,
        contradictions: result.contradictions,
        feedback: result.feedback,
      });
      onUpdate(result.session);
      if (result.finished) message.success("这一场问完了，复盘已生成");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交失败");
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      onUpdate(await finishDrill(session.id));
      message.success("已结束，复盘已生成");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "结束失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {lastVerdict && (
        <Alert
          type={
            lastVerdict.status === "verified"
              ? "success"
              : lastVerdict.status === "contradictory"
                ? "error"
                : "warning"
          }
          showIcon
          message={`上一轮判定：${EVIDENCE_LABELS[lastVerdict.status]}`}
          description={
            <Space direction="vertical" size={2}>
              {/* 真实模拟模式下不展示"还缺什么"——那等于把判分标准念出来。 */}
              {deferred && lastVerdict.feedback === "" ? (
                <Typography.Text type="secondary">
                  真实模拟模式：判定已记录，结束后统一复盘。
                </Typography.Text>
              ) : (
                <>
                  {lastVerdict.feedback && <span>{lastVerdict.feedback}</span>}
                  {lastVerdict.missing.length > 0 && (
                    <span>还缺：{lastVerdict.missing.join("；")}</span>
                  )}
                  {lastVerdict.contradictions.length > 0 && (
                    <span>矛盾：{lastVerdict.contradictions.join("；")}</span>
                  )}
                </>
              )}
            </Space>
          }
        />
      )}

      {pending ? (
        <Card size="small" title={`第 ${session.current_index} / ${session.max_questions} 题`}>
          <Space direction="vertical" size={10} style={{ width: "100%" }}>
            <Typography.Title level={5} style={{ margin: 0 }}>
              {pending.question}
            </Typography.Title>

            {pending.followup_depth > 0 && (
              <Tag color="purple">这是对同一条主张的第 {pending.followup_depth + 1} 次追问</Tag>
            )}

            {/* 契约对整个会话可见：用户有权知道自己在被怎么衡量。 */}
            <details className="drill-contract">
              <summary>这道题的评分标准（提问前已锁定）</summary>
              <Space direction="vertical" size={4} style={{ marginTop: 8 }}>
                {pending.intent && (
                  <Typography.Text type="secondary">想验证：{pending.intent}</Typography.Text>
                )}
                <div>
                  <Typography.Text type="secondary">必须讲到：</Typography.Text>
                  <ul className="drill-contract-list">
                    {pending.required_evidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                {pending.followup_triggers.length > 0 && (
                  <div>
                    <Typography.Text type="secondary">出现这些就该被追问：</Typography.Text>
                    <ul className="drill-contract-list">
                      {pending.followup_triggers.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {pending.next_followup_kind && (
                  <Typography.Text type="secondary">
                    下一问方向：{FOLLOWUP_LABELS[pending.next_followup_kind as never] ?? ""}
                  </Typography.Text>
                )}
              </Space>
            </details>

            <Input.TextArea
              rows={5}
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              disabled={busy}
              placeholder="照实说你做过什么。没做到的就说没做到——这里不会替你编，编了也是面试时要还的。"
            />
            <Space>
              <Button type="primary" loading={busy} onClick={() => void submit()}>
                提交回答
              </Button>
              <Popconfirm
                title="结束这一场并出复盘？"
                description="已经答过的判定都会保留。"
                okText="结束并出复盘"
                cancelText="继续答"
                onConfirm={() => void stop()}
              >
                <Button disabled={busy}>提前结束</Button>
              </Popconfirm>
            </Space>
          </Space>
        </Card>
      ) : (
        <Alert
          type="info"
          showIcon
          message="正在生成下一题…"
          description="如果长时间没有变化，可以点「提前结束」先拿现有的判定出复盘。"
          action={
            <Button size="small" loading={busy} onClick={() => void stop()}>
              提前结束
            </Button>
          }
        />
      )}

      {session.turns.length > 0 && (
        <details className="drill-transcript">
          <summary>逐轮记录（{session.turns.length} 轮）</summary>
          <List
            size="small"
            style={{ marginTop: 8 }}
            dataSource={session.turns}
            renderItem={(turn) => (
              <List.Item>
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <Typography.Text strong>问：{turn.question}</Typography.Text>
                  <Typography.Text>答：{turn.answer}</Typography.Text>
                  {turn.status && (
                    <Space size={6}>
                      {evidenceTag(turn.status as EvidenceStatus)}
                      {turn.feedback && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {turn.feedback}
                        </Typography.Text>
                      )}
                    </Space>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </details>
      )}
    </Space>
  );
}

export default function DrillPage() {
  const { message } = App.useApp();
  const [current, setCurrent] = useState<DrillSession | null>(null);
  const [history, setHistory] = useState<DrillSessionBrief[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);

  // 用 ref 读"当前是否已打开某一场"：把它写进 refreshHistory 的依赖会让回调
  // 每次都重建，而 refreshHistory 又是 useEffect 的依赖 → 无限重取。
  const currentRef = useRef<DrillSession | null>(null);
  currentRef.current = current;

  const refreshHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const records = await listDrillSessions();
      setHistory(records);
      // 自动打开最近一场**进行中**的：用户回到这一页最可能是想接着答，
      // 让他再点一次「继续」是多余的一步。没有进行中的就不自动打开，
      // 免得把一份旧复盘糊在屏幕上。
      const active = records.find((item) => item.status === "active");
      if (active && !currentRef.current) {
        setCurrent(await getDrillSession(active.id));
        setOpenId(active.id);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取记录失败");
    } finally {
      setLoadingHistory(false);
    }
  }, [message]);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

  const openHistory = async (id: number) => {
    try {
      setOpenId(id);
      setCurrent(await getDrillSession(id));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取失败");
    }
  };

  const remove = async (id: number) => {
    try {
      await deleteDrillSession(id);
      message.success("已删除");
      if (current?.id === id) setCurrent(null);
      await refreshHistory();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const stats = useMemo(() => {
    if (!current) return null;
    return current.summary;
  }, [current]);

  const finished = current?.status === "finished";

  return (
    <div className="drill-page">
      <div className="drill-page-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            面试深挖
          </Typography.Title>
          <Typography.Text type="secondary">
            把台账里「已确认」的主张逐条拿出来压力测试：讲不讲得清、哪里还站不住。
            每道题的标准在你看到问题之前就定下来，不评总分。
          </Typography.Text>
        </Space>
        <StartPanel
          onStarted={(session) => {
            setCurrent(session);
            setOpenId(session.id);
            void refreshHistory();
          }}
        />
      </div>

      {current && stats && (
        <div className="drill-summary">
          <Statistic title="已问" value={stats.questions} />
          <Statistic
            title="讲得清"
            value={stats.verified_count}
            valueStyle={{ color: "#389e0d" }}
            prefix={<CheckCircleOutlined />}
          />
          <Statistic
            title="部分验证"
            value={stats.partial_count}
            valueStyle={{ color: "#d48806" }}
          />
          <Statistic title="未验证" value={stats.unverified_count} />
          {stats.contradictory_count > 0 && (
            <Statistic
              title="存在矛盾"
              value={stats.contradictory_count}
              valueStyle={{ color: "#cf1322" }}
              prefix={<ExclamationCircleOutlined />}
            />
          )}
        </div>
      )}

      {current && (
        <Card
          size="small"
          title={current.title}
          extra={
            <Space>
              <Tag color={finished ? "default" : "processing"}>
                {finished ? "已结束" : "进行中"}
              </Tag>
              <Tooltip title={FEEDBACK_LABELS[current.feedback_policy]}>
                <Tag>{current.feedback_policy === "deferred" ? "真实模拟" : "训练模式"}</Tag>
              </Tooltip>
            </Space>
          }
        >
          {finished ? (
            <ReviewPanel session={current} />
          ) : (
            <ActiveSession session={current} onUpdate={setCurrent} />
          )}
        </Card>
      )}

      <Card
        size="small"
        title="历史记录"
        extra={
          <Button size="small" onClick={() => void refreshHistory()} loading={loadingHistory}>
            刷新
          </Button>
        }
      >
        {loadingHistory ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : history.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="还没有深挖记录。先在「事实台账」确认几条主张，再回来开一场。"
          />
        ) : (
          <List
            size="small"
            dataSource={history}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="open"
                    size="small"
                    type="link"
                    onClick={() => void openHistory(item.id)}
                  >
                    {item.status === "active" ? "继续" : "看复盘"}
                  </Button>,
                  <Popconfirm
                    key="del"
                    title="删除这场深挖？"
                    okText="确认删除"
                    cancelText="取消"
                    onConfirm={() => void remove(item.id)}
                  >
                    <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>,
                ]}
              >
                <Space size={8} wrap>
                  <Typography.Text strong={openId === item.id}>{item.title}</Typography.Text>
                  <Tag color={item.status === "active" ? "processing" : "default"}>
                    {item.status === "active" ? "进行中" : "已结束"}
                  </Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {item.current_index}/{item.max_questions} 题 ·{" "}
                    {item.created_at.replace("T", " ").slice(0, 16)}
                  </Typography.Text>
                </Space>
              </List.Item>
            )}
          />
        )}
      </Card>

      {!current && history.length > 0 && (
        <Typography.Text type="secondary">
          点上方「继续」或「看复盘」打开某一场；也可以
          <PlusOutlined /> 直接开始新的一场。
        </Typography.Text>
      )}
    </div>
  );
}
