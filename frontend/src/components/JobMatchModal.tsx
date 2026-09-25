/**
 * 岗位匹配度分析弹窗：把 JD 与**你已确认的资料 / 简历**逐条对照。
 *
 * 与「岗位需求解读」并列但性质不同——解读只读招聘原文（"这岗位要什么"），
 * 这里会读取个人资料与简历（"我够不够"），所以标题与说明都明确写出这一区别。
 *
 * 三条硬约束（设计 §9）：
 * - **五类结论本身不渲染任何百分比 / 评分**——模型给出的判断只有"到没到"这一层，
 *   给它配一个数字会让人以为存在一个客观分数；
 * - 准入结论只读后端返回的 `admission`，前端不自行再判一次；
 * - 证据不足的条目如实写"资料中未提供"，不替模型补事实。
 *
 * **与「匹配度参考分」的区别（别把两者混起来）**：参考分是后端用**纯本地规则**现算的
 * 派生值（技能覆盖 / 年限 / 项目相关度 / 硬性门槛 / JD 关键词覆盖五个分项加权），
 * **不调用模型、不落库、也不参与投递准入**，并且**强制展示后端下发的免责文案**。
 * 它放在五类结论**之后**作为补充，且不给分数配"好/差"的颜色分级——后端没有定义档位，
 * 前端自己划一条线就是在编造一个判断。
 */
import { BulbOutlined, DeleteOutlined, ReloadOutlined, RobotOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Empty,
  Modal,
  Progress,
  Space,
  Skeleton,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { deleteJobMatch, generateJobMatch, getJobMatch } from "../api/jobs";
import { announceBackgroundFailure, announceBackgroundResult } from "../utils/backgroundTask";
import {
  ADMISSION_META,
  MATCH_STATUS_META,
  type HardGateResult,
  type Job,
  type JobMatchOut,
  type MatchCondition,
} from "../types";

interface Props {
  job: Job | null;
  onClose: () => void;
}

const HARD_GATE_LABELS: Record<HardGateResult, { label: string; color: string }> = {
  met: { label: "硬性条件已满足", color: "green" },
  unmet: { label: "硬性条件未满足", color: "red" },
  unknown: { label: "硬性条件待确认", color: "gold" },
};

const GROUPS: {
  key: keyof Pick<JobMatchOut["result"], "hard_conditions" | "core_abilities" | "bonus_items">;
  title: string;
}[] = [
  { key: "hard_conditions", title: "硬性条件" },
  { key: "core_abilities", title: "核心能力" },
  { key: "bonus_items", title: "加分项" },
];

function ConditionList({ conditions }: { conditions: MatchCondition[] }) {
  if (conditions.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无条目" />;
  }
  return (
    <ul className="job-match-conditions">
      {conditions.map((condition, index) => {
        const meta = MATCH_STATUS_META[condition.status];
        return (
          <li key={`${condition.label}-${index}`} className="job-match-condition">
            <Space wrap size={8}>
              <Tag color={meta.color}>{meta.label}</Tag>
              <Typography.Text strong>{condition.label}</Typography.Text>
            </Space>
            {condition.jd_quote && (
              <Typography.Paragraph type="secondary" className="job-match-quote">
                招聘原文：{condition.jd_quote}
              </Typography.Paragraph>
            )}
            <Typography.Paragraph className="job-match-evidence">
              依据：{condition.evidence || "资料中未提供"}
            </Typography.Paragraph>
          </li>
        );
      })}
    </ul>
  );
}

export default function JobMatchModal({ job, onClose }: Props) {
  const { message } = App.useApp();
  const [data, setData] = useState<JobMatchOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const version = useRef(0);
  const lastJobId = useRef<number | null>(null);

  useEffect(() => {
    if (!job || lastJobId.current === job.id) return;
    lastJobId.current = job.id;
    version.current += 1;
    setData(null);
    setError("");
    setLoading(false);
  }, [job]);

  const load = useCallback(async () => {
    if (!job) return;
    const current = ++version.current;
    setLoading(true);
    setError("");
    try {
      const result = await getJobMatch(job.id);
      if (current === version.current) setData(result);
    } catch (loadError) {
      if (current === version.current) {
        setError(loadError instanceof Error ? loadError.message : "读取匹配分析失败，请稍后重试");
      }
    } finally {
      if (current === version.current) setLoading(false);
    }
  }, [job]);

  useEffect(() => {
    if (job) void load();
  }, [job, load]);

  // 用户在分析过程中关掉了弹窗：请求照跑，完成后用通知告诉他（见 utils/backgroundTask）。
  const leftWhileAnalyzing = useRef(false);

  const analyze = async () => {
    if (!job) return;
    setAnalyzing(true);
    setError("");
    leftWhileAnalyzing.current = false;
    try {
      await generateJobMatch(job.id, data != null && data.id > 0);
      if (leftWhileAnalyzing.current) {
        announceBackgroundResult("匹配度分析", "回到岗位详情再点「匹配度分析」即可看到结论。");
        return;
      }
      await load();
    } catch (analyzeError) {
      const detail =
        analyzeError instanceof Error ? analyzeError.message : "生成匹配分析失败，请稍后重试";
      if (leftWhileAnalyzing.current) {
        announceBackgroundFailure("匹配度分析", detail);
        return;
      }
      setError(detail);
    } finally {
      if (!leftWhileAnalyzing.current) setAnalyzing(false);
    }
  };

  const clear = async () => {
    if (!job) return;
    setAnalyzing(true);
    try {
      await deleteJobMatch(job.id);
      message.success("已清除该岗位的匹配结论");
      setData(null);
      await load();
    } catch (clearError) {
      message.error(clearError instanceof Error ? clearError.message : "清除失败");
    } finally {
      setAnalyzing(false);
    }
  };

  const hasResult = data != null && data.id > 0;
  const result = hasResult ? data.result : null;
  const admissionMeta = result ? ADMISSION_META[result.admission] : null;
  const hardGateMeta = result ? HARD_GATE_LABELS[result.hard_gate] : null;

  return (
    <Modal
      title={
        <Space direction="vertical" size={0}>
          <Space>
            <RobotOutlined />
            岗位匹配度分析
          </Space>
          <Typography.Text type="secondary" className="job-match-subtitle">
            对照你已保存的个人资料与简历逐条判断（与只读招聘原文的「岗位需求解读」不同）
          </Typography.Text>
        </Space>
      }
      open={!!job}
      onCancel={onClose}
      footer={null}
      width={760}
      destroyOnHidden
    >
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          style={{ marginBottom: 12 }}
          action={
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>
              重试
            </Button>
          }
        />
      )}

      {analyzing ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="分析期间可以关掉这个窗口去做别的，完成后会弹通知并响一声（只要页面没刷新）。"
        />
      ) : null}

      {loading && !data ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : !hasResult ? (
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这个岗位还没有做过匹配分析" />
          <Typography.Paragraph type="secondary">
            分析会读取你的个人资料与简历，对每条招聘要求给出「已匹配 / 表达缺口 / 证据不足 /
            真实缺口 / 待确认」五类结论。未配置大模型时会走本地降级（各条均为「待确认」），
            不假装做过 AI 比对。
          </Typography.Paragraph>
          <Button
            type="primary"
            icon={<BulbOutlined />}
            loading={analyzing}
            onClick={() => void analyze()}
          >
            开始分析
          </Button>
        </Space>
      ) : (
        result && (
          <div className="job-match-content">
            <Descriptions size="small" column={2} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="该岗位">
                {data.company ? `${data.company} · ` : ""}
                {data.job_title}
              </Descriptions.Item>
              <Descriptions.Item label="分析模型">
                {data.model || "本地降级（未配置大模型）"}
              </Descriptions.Item>
              <Descriptions.Item label="准入结论">
                {admissionMeta && <Tag color={admissionMeta.color}>{admissionMeta.label}</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="硬性门槛">
                {hardGateMeta && <Tag color={hardGateMeta.color}>{hardGateMeta.label}</Tag>}
              </Descriptions.Item>
            </Descriptions>

            {result.admission === "block" && (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 12 }}
                message="存在真实缺口：默认不自动投递，需要你在加入投递台时逐条确认。"
              />
            )}
            {result.admission === "needs_confirm" && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="含证据不足或待确认的条目：加入投递台时需要你逐条确认。"
              />
            )}

            {GROUPS.map((group) => (
              <section key={group.key} className="job-match-group">
                <Typography.Title level={5}>{group.title}</Typography.Title>
                <ConditionList conditions={result[group.key]} />
              </section>
            ))}

            {result.advice && (
              <>
                <Typography.Title level={5}>投递建议</Typography.Title>
                <Typography.Paragraph>{result.advice}</Typography.Paragraph>
              </>
            )}

            {/* 参考分放在五类结论**之后**：它只是补充感知"差多少"，不能盖过准入结论。
                分数用单一色相画（不按高低变色）：后端没有定义档位，前端自己划"好/差"的线
                就是在编造一个它没有的判断。 */}
            {data.reference_score && (
              <section className="job-match-score">
                <Typography.Title level={5}>匹配度参考分</Typography.Title>
                <div className="job-match-score-head">
                  <Progress
                    type="circle"
                    size={72}
                    percent={data.reference_score.score}
                    format={(value) => <span className="job-match-score-value">{value}</span>}
                  />
                  <Typography.Paragraph type="secondary" className="job-match-score-disclaimer">
                    {data.reference_score.disclaimer}
                  </Typography.Paragraph>
                </div>
                <ul className="job-match-score-dimensions">
                  {data.reference_score.dimensions.map((dimension) => (
                    <li key={dimension.key}>
                      <div className="job-match-score-line">
                        <span className="job-match-score-label">{dimension.label}</span>
                        <Progress percent={dimension.score} showInfo={false} size="small" />
                        <span className="job-match-score-value">{dimension.score}</span>
                      </div>
                      {dimension.evidence && (
                        <Typography.Text type="secondary">{dimension.evidence}</Typography.Text>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {result.notes.length > 0 && (
              <>
                <Typography.Title level={5}>口径说明</Typography.Title>
                <ul className="job-match-notes">
                  {result.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </>
            )}

            <Space wrap style={{ marginTop: 12 }}>
              <Button icon={<ReloadOutlined />} loading={analyzing} onClick={() => void analyze()}>
                重新分析
              </Button>
              <Button
                danger
                icon={<DeleteOutlined />}
                loading={analyzing}
                onClick={() => void clear()}
              >
                清除结论
              </Button>
            </Space>
          </div>
        )
      )}
    </Modal>
  );
}
