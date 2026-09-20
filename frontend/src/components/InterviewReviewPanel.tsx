/** 面试复盘（R-11 补）：录入真实被问问题 → 分析答题思路 → 反向优化简历。
 *
 * 复用已就绪的 analyzeInterviewQuestion / optimizeResumeFromInterview 接口，不另造。反向优化只产出
 * 建议列表、不改正文。分析出思路后**自动保存**为历史（无需手点保存），也保留「保存复盘」按钮。
 *
 * 历史记录富还原：传入 record 后用与刚生成时相同的渲染路径展示，「反向优化简历」按钮可点、生成结果
 * 写回同一条记录。旧版纯文本记录（analysis 为字符串）仅做兼容展示并提示"仅可查看"。
 */
import {
  BulbOutlined,
  DeleteOutlined,
  HistoryOutlined,
  SaveOutlined,
  SendOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  List,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import {
  analyzeInterviewQuestion,
  deleteReview,
  listReviews,
  optimizeResumeFromInterview,
  saveReview,
  updateReview,
} from "../api/interview";
import { RowActions } from "./common/RowActions";
import { useApi } from "../hooks/useApi";
import type { InterviewAnalysis, InterviewOptimizeResult, InterviewReviewRecord } from "../types";

interface Option {
  value: number;
  label: string;
}

interface Props {
  jobOptions: Option[];
  resumeOptions: Option[];
  onGoToResume?: () => void;
  /** 历史记录富还原：传入一条已保存的复盘记录后，用相同的渲染路径展示并允许「反向优化简历」回写。 */
  record?: InterviewReviewRecord | null;
  /** 点击历史条目里的「查看详情」时回调，由父组件接管选中。 */
  onOpenRecord?: (record: InterviewReviewRecord) => void;
  /** 退出历史查看时回调。 */
  onCloseRecord?: () => void;
}

export default function InterviewReviewPanel({
  jobOptions,
  resumeOptions,
  onGoToResume,
  record,
  onOpenRecord,
  onCloseRecord,
}: Props) {
  const { message } = App.useApp();
  const [question, setQuestion] = useState("");
  const [jobId, setJobId] = useState<number | undefined>();
  const [resumeId, setResumeId] = useState<number | undefined>();
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<InterviewAnalysis | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [optimizeResult, setOptimizeResult] = useState<InterviewOptimizeResult | null>(null);
  const [saving, setSaving] = useState(false);
  const reviews = useApi(listReviews, []);

  // 历史富还原：用历史记录的 analysis/suggestions 充当展示数据。
  // 旧版纯文本记录（analysis 为字符串）不是结构化对象，不能当 analysis 用，置空以免渲染时崩。
  const viewAnalysis: InterviewAnalysis | null = record
    ? typeof record.analysis === "string"
      ? null
      : (record.analysis as InterviewAnalysis)
    : analysis;
  // 建议展示：刚生成的 optimizeResult 优先（含记录模式下反向优化新产出的建议），否则回退历史记录里已持久化的建议。
  const viewSuggestions: InterviewOptimizeResult["suggestions"] = optimizeResult?.suggestions
    ? optimizeResult.suggestions
    : record
      ? (record.suggestions as InterviewOptimizeResult["suggestions"])
      : [];

  // 旧版纯文本记录（analysis 为字符串）兼容：只展示提示，不崩。
  const legacyText = record && typeof record.analysis === "string" ? record.analysis : null;

  // 打开历史记录时，用其中持久化的分析与建议填充展示状态（不重新调用模型），并预填关联的岗位/简历。
  useEffect(() => {
    if (!record) return;
    setAnalysis((record.analysis as InterviewAnalysis) ?? null);
    setOptimizeResult(
      record.suggestions && record.suggestions.length
        ? {
            resume_id: record.resume_id ?? 0,
            suggestions: record.suggestions,
            llm_used: true,
            notes: [],
          }
        : null,
    );
    if (record.job_id) setJobId(record.job_id);
    if (record.resume_id) setResumeId(record.resume_id);
  }, [record]);

  const analyze = async () => {
    if (!record && !question.trim()) {
      message.error("请先录入真实被问的问题");
      return;
    }
    setAnalyzing(true);
    try {
      const result = await analyzeInterviewQuestion({
        question: (record?.questions?.[0] ?? question).trim(),
        job_id: jobId ?? null,
        resume_id: resumeId ?? null,
      });
      setAnalysis(result);
      setOptimizeResult(null);
      // 分析出思路后自动保存为历史（无需用户手点保存）。
      await persistReview(result, []);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "分析答题思路失败");
    } finally {
      setAnalyzing(false);
    }
  };

  const persistReview = async (
    analysisObj: InterviewAnalysis,
    suggestions: InterviewOptimizeResult["suggestions"],
  ) => {
    setSaving(true);
    try {
      await saveReview({
        job_id: jobId ?? null,
        job_title: jobOptions.find((option) => option.value === jobId)?.label ?? "",
        company: "",
        resume_id: resumeId ?? null,
        resume_title: resumeOptions.find((option) => option.value === resumeId)?.label ?? "",
        questions: analysisObj.question ? [analysisObj.question] : [],
        analysis: analysisObj,
        suggestions: suggestions ?? [],
        model: "",
      });
      await reviews.reload();
    } catch (error) {
      message.warning(error instanceof Error ? error.message : "自动保存复盘历史失败");
    } finally {
      setSaving(false);
    }
  };

  const saveReviewRecord = async () => {
    if (!analysis || saving) return;
    await persistReview(analysis, optimizeResult?.suggestions ?? []);
  };

  const optimize = async () => {
    if (!resumeId) {
      message.error("请先选择要优化的简历");
      return;
    }
    if (!viewAnalysis) {
      message.error("请先分析答题思路");
      return;
    }
    setOptimizing(true);
    try {
      const result = await optimizeResumeFromInterview({
        resume_id: resumeId,
        job_id: jobId ?? null,
        weaknesses: viewAnalysis.pitfalls,
        follow_ups: viewAnalysis.follow_up,
      });
      setOptimizeResult(result);
      // 历史记录富还原：把新生成的建议写回同一条记录。
      if (record) {
        try {
          await updateReview(record.id, {
            analysis: viewAnalysis,
            suggestions: result.suggestions,
          });
        } catch (error) {
          message.warning(error instanceof Error ? error.message : "建议已生成，但写回历史失败");
        }
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : "反向优化失败");
    } finally {
      setOptimizing(false);
    }
  };

  const removeReview = async (id: number) => {
    try {
      await deleteReview(id);
      message.success("已删除复盘历史");
      await reviews.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除复盘历史失败");
    }
  };

  const priorityColor = (priority: string) =>
    priority === "high" ? "red" : priority === "medium" ? "gold" : "default";

  const reviewItems = (reviews.data ?? []).map((review) => ({
    key: String(review.id),
    label: (
      <Space wrap>
        <span>{review.resume_title || review.job_title || "复盘"}</span>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {review.created_at.replace("T", " ").slice(0, 16)}
        </Typography.Text>
      </Space>
    ),
    children: (
      <Space direction="vertical" style={{ width: "100%" }}>
        {review.questions.length > 0 && (
          <>
            <Typography.Text strong>真实问题</Typography.Text>
            <ul style={{ paddingLeft: 20, margin: "4px 0" }}>
              {review.questions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        )}
        {review.analysis?.framework && (
          <Typography.Paragraph style={{ margin: 0 }}>
            {review.analysis.framework}
          </Typography.Paragraph>
        )}
        {review.suggestions.length > 0 && (
          <>
            <Typography.Text strong>简历改进建议</Typography.Text>
            <ul style={{ paddingLeft: 20, margin: "4px 0" }}>
              {review.suggestions.map((item) => (
                <li key={item.suggestion}>{item.suggestion}</li>
              ))}
            </ul>
          </>
        )}
        <Space wrap>
          {onOpenRecord && (
            <Button size="small" onClick={() => onOpenRecord(review)}>
              查看详情
            </Button>
          )}
          <RowActions
            more={[
              {
                key: "delete",
                label: "删除复盘历史",
                danger: true,
                icon: <DeleteOutlined />,
                confirm: "删除这条复盘历史？",
                onClick: () => void removeReview(review.id),
              },
            ]}
          />
        </Space>
      </Space>
    ),
  }));

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      {record && (
        <Alert
          type="info"
          showIcon
          message={`正在查看历史复盘 #${record.id}（${record.created_at.replace("T", " ").slice(0, 16)}）`}
          action={
            onCloseRecord && (
              <Button size="small" onClick={onCloseRecord}>
                返回
              </Button>
            )
          }
        />
      )}

      {!record && (
        <Card size="small" title="面试复盘">
          <Space direction="vertical" style={{ width: "100%" }} size={8}>
            <Input.TextArea
              value={question}
              autoSize={{ minRows: 2, maxRows: 4 }}
              placeholder="录入面试里真实被问的问题，例如：你这个项目的难点是怎么解决的？"
              onChange={(event) => setQuestion(event.target.value)}
            />
            <Space wrap>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ minWidth: 220 }}
                placeholder="关联岗位（选填）"
                value={jobId}
                onChange={setJobId}
                options={jobOptions}
              />
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ minWidth: 220 }}
                placeholder="关联简历（反向优化必选）"
                value={resumeId}
                onChange={setResumeId}
                options={resumeOptions}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={analyzing}
                onClick={() => void analyze()}
              >
                分析答题思路
              </Button>
            </Space>
          </Space>
        </Card>
      )}

      {viewAnalysis ? (
        <Card size="small" title="答题思路">
          <Typography.Paragraph strong>{viewAnalysis.framework}</Typography.Paragraph>
          {viewAnalysis.key_points.length > 0 && (
            <>
              <Typography.Text strong>要点</Typography.Text>
              <ul>
                {viewAnalysis.key_points.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {viewAnalysis.follow_up.length > 0 && (
            <>
              <Typography.Text strong>可能的追问</Typography.Text>
              <ul>
                {viewAnalysis.follow_up.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {viewAnalysis.pitfalls.length > 0 && (
            <>
              <Typography.Text strong>常见误区</Typography.Text>
              <ul>
                {viewAnalysis.pitfalls.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
          <Space wrap style={{ marginTop: 12 }}>
            {record && (
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ minWidth: 220 }}
                placeholder="关联简历（反向优化必选）"
                value={resumeId}
                onChange={setResumeId}
                options={resumeOptions}
              />
            )}
            <Button
              icon={<ThunderboltOutlined />}
              loading={optimizing}
              onClick={() => void optimize()}
            >
              反向优化简历
            </Button>
            {!record && (
              <Button
                icon={<SaveOutlined />}
                loading={saving}
                onClick={() => void saveReviewRecord()}
              >
                保存复盘
              </Button>
            )}
            <Typography.Text type="secondary">只产出建议列表，不直接改简历正文。</Typography.Text>
          </Space>
        </Card>
      ) : (
        !record && (
          <Empty description="录入问题后，先分析答题思路" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )
      )}

      {legacyText ? (
        <Card size="small" title="历史复盘">
          <Alert
            type="warning"
            showIcon
            message="此为旧版记录，仅可查看"
            description="旧版历史以纯文本保存，无法还原为结构化复盘，仅展示原始内容。"
          />
          <Typography.Paragraph style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
            {legacyText}
          </Typography.Paragraph>
        </Card>
      ) : (
        viewSuggestions.length > 0 && (
          <Card size="small" title="简历改进建议">
            {viewSuggestions.length === 0 ? (
              <Alert
                type="info"
                showIcon
                message="没有产出建议，试试补充更多面试暴露的短板或追问"
              />
            ) : (
              <List
                dataSource={viewSuggestions}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <Space size={6} wrap>
                          <Tag color={priorityColor(item.priority)}>{item.priority}</Tag>
                          <span>{item.section}</span>
                          <Typography.Text type="secondary">{item.issue}</Typography.Text>
                        </Space>
                      }
                      description={
                        <Space direction="vertical" size={2} style={{ width: "100%" }}>
                          <span>
                            <BulbOutlined /> {item.suggestion}
                          </span>
                          {item.evidence.length > 0 && (
                            <Typography.Text type="secondary">
                              依据：{item.evidence.join("；")}
                            </Typography.Text>
                          )}
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
            {onGoToResume && (
              <Button type="link" style={{ paddingLeft: 0 }} onClick={onGoToResume}>
                去简历中心对照修改 →
              </Button>
            )}
          </Card>
        )
      )}

      <Card
        size="small"
        title={
          <Space>
            <HistoryOutlined />
            历史复盘
          </Space>
        }
      >
        {reviews.loading && !reviews.data ? (
          <Alert type="info" showIcon message="加载中…" />
        ) : reviews.error ? (
          <Alert type="error" showIcon message={reviews.error} />
        ) : (reviews.data ?? []).length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有保存过复盘" />
        ) : (
          <Collapse items={reviewItems} />
        )}
      </Card>
    </Space>
  );
}
