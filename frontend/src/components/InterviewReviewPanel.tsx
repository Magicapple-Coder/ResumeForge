/** 面试复盘（R-11 补）：录入真实被问问题 → 分析答题思路 → 反向优化简历。
 *
 * 复用 T04a 已就绪的 ``analyzeInterviewQuestion`` / ``optimizeResumeFromInterview`` 接口，
 * 不另造。反向优化只产出建议列表、不改正文；「去简历中心回填」由父组件决定跳转去向。
 *
 * D5 补充：分析出思路后可点「保存复盘」把「问题 + 思路 + 建议」落成历史；下方「历史复盘」
 * 回看某次复盘并删除（删除是软删，彻底删除在回收站里另做）。
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
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import {
  analyzeInterviewQuestion,
  deleteReview,
  listReviews,
  optimizeResumeFromInterview,
  saveReview,
} from "../api/interview";
import { useApi } from "../hooks/useApi";
import type { InterviewAnalysis, InterviewOptimizeResult } from "../types";

interface Option {
  value: number;
  label: string;
}

interface Props {
  jobOptions: Option[];
  resumeOptions: Option[];
  onGoToResume?: () => void;
}

export default function InterviewReviewPanel({ jobOptions, resumeOptions, onGoToResume }: Props) {
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

  const analyze = async () => {
    if (!question.trim()) {
      message.error("请先录入真实被问的问题");
      return;
    }
    setAnalyzing(true);
    try {
      setAnalysis(
        await analyzeInterviewQuestion({
          question: question.trim(),
          job_id: jobId ?? null,
          resume_id: resumeId ?? null,
        }),
      );
      setOptimizeResult(null);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "分析答题思路失败");
    } finally {
      setAnalyzing(false);
    }
  };

  const optimize = async () => {
    if (!resumeId) {
      message.error("请先选择要优化的简历");
      return;
    }
    if (!analysis) {
      message.error("请先分析答题思路");
      return;
    }
    setOptimizing(true);
    try {
      setOptimizeResult(
        await optimizeResumeFromInterview({
          resume_id: resumeId,
          job_id: jobId ?? null,
          weaknesses: analysis.pitfalls,
          follow_ups: analysis.follow_up,
        }),
      );
    } catch (error) {
      message.error(error instanceof Error ? error.message : "反向优化失败");
    } finally {
      setOptimizing(false);
    }
  };

  const saveReviewRecord = async () => {
    if (!analysis || saving) return;
    setSaving(true);
    try {
      await saveReview({
        job_id: jobId ?? null,
        job_title: jobOptions.find((option) => option.value === jobId)?.label ?? "",
        company: "",
        resume_id: resumeId ?? null,
        resume_title: resumeOptions.find((option) => option.value === resumeId)?.label ?? "",
        questions: analysis.question ? [analysis.question] : [],
        analysis,
        suggestions: optimizeResult?.suggestions ?? [],
        model: "",
      });
      message.success("复盘已保存到历史");
      await reviews.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存复盘失败");
    } finally {
      setSaving(false);
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
        <Popconfirm
          title="删除这条复盘历史？"
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true, "aria-label": `确认删除复盘历史 ${review.id}` }}
          onConfirm={() => void removeReview(review.id)}
        >
          <Button size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      </Space>
    ),
  }));

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
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

      {analysis ? (
        <Card size="small" title="答题思路">
          <Typography.Paragraph strong>{analysis.framework}</Typography.Paragraph>
          {analysis.key_points.length > 0 && (
            <>
              <Typography.Text strong>要点</Typography.Text>
              <ul>
                {analysis.key_points.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {analysis.follow_up.length > 0 && (
            <>
              <Typography.Text strong>可能的追问</Typography.Text>
              <ul>
                {analysis.follow_up.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {analysis.pitfalls.length > 0 && (
            <>
              <Typography.Text strong>常见误区</Typography.Text>
              <ul>
                {analysis.pitfalls.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
          <Space wrap style={{ marginTop: 12 }}>
            <Button
              icon={<ThunderboltOutlined />}
              loading={optimizing}
              onClick={() => void optimize()}
            >
              反向优化简历
            </Button>
            <Button icon={<SaveOutlined />} loading={saving} onClick={() => void saveReviewRecord()}>
              保存复盘
            </Button>
            <Typography.Text type="secondary">
              只产出建议列表，不直接改简历正文。
            </Typography.Text>
          </Space>
        </Card>
      ) : (
        <Empty description="录入问题后，先分析答题思路" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}

      {optimizeResult && (
        <Card size="small" title="简历改进建议">
          {optimizeResult.suggestions.length === 0 ? (
            <Alert type="info" showIcon message="没有产出建议，试试补充更多面试暴露的短板或追问" />
          ) : (
            <List
              dataSource={optimizeResult.suggestions}
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
