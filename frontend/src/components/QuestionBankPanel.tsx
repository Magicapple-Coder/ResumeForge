/** 个性化题库（R-11）：基于岗位 + 简历 + 台账基线即时生成三类题。
 *
 * 只展示后端算好的题目，**即时计算、不落库**。「开始模拟面试」把题目交回面试会话
 * （由父组件把题目写进面试的考察重点，而不是在这里新建面试）。
 *
 * D5 补充：生成结果可点「保存题库」落成历史；下方「历史题库」回看某次生成的三类题并删除
 * （删除是软删，彻底删除在回收站里另做）。
 */
import {
  BulbOutlined,
  DeleteOutlined,
  HistoryOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Empty,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import {
  deleteQuestionBank,
  generateQuestionAnswer,
  generateQuestionBank,
  listQuestionBanks,
  saveQuestionBank,
} from "../api/interview";
import { useApi } from "../hooks/useApi";
import { QUESTION_BANK_TYPES } from "../types";
import type { QuestionAnswer, QuestionBankOut } from "../types";

interface Props {
  jobOptions: { value: number; label: string }[];
  resumeOptions: { value: number; label: string }[];
  onStartSession?: (questions: string[]) => void;
}

export default function QuestionBankPanel({ jobOptions, resumeOptions, onStartSession }: Props) {
  const { message } = App.useApp();
  const [jobId, setJobId] = useState<number | undefined>();
  const [resumeId, setResumeId] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<QuestionBankOut | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  // 单题参考答案：按「分组-序号」键控，展开即缓存，收起即丢弃；不落库、不自动发送。
  const [answerMap, setAnswerMap] = useState<Record<string, QuestionAnswer>>({});
  const [answerLoading, setAnswerLoading] = useState<string | null>(null);
  const [answerError, setAnswerError] = useState("");
  const banks = useApi(listQuestionBanks, []);

  const generate = async () => {
    if (loading) return;
    if (!jobId && !resumeId) {
      setError("请至少选择一个岗位或一份简历，题库才能有针对性");
      setData(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setData(await generateQuestionBank({ job_id: jobId ?? null, resume_id: resumeId ?? null }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成题库失败");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const startSession = () => {
    if (!data || !onStartSession) return;
    const questions = data.groups.flatMap((group) =>
      group.questions.map((item) => item.question),
    );
    onStartSession(questions);
  };

  const saveBank = async () => {
    if (!data || saving) return;
    setSaving(true);
    try {
      const resumeTitle =
        resumeOptions.find((option) => option.value === data.resume_id)?.label ?? "";
      await saveQuestionBank({
        job_id: data.job_id ?? null,
        job_title: data.job_title,
        company: data.company,
        resume_id: data.resume_id ?? null,
        resume_title: resumeTitle,
        groups: data.groups,
        model: "",
      });
      message.success("题库已保存到历史");
      await banks.reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存题库失败");
    } finally {
      setSaving(false);
    }
  };

  const removeBank = async (id: number) => {
    try {
      await deleteQuestionBank(id);
      message.success("已删除题库历史");
      await banks.reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除题库历史失败");
    }
  };

  /** 展开/收起某道题的参考答案；展开时带上当前选中的岗位与简历作为背景。 */
  const toggleAnswer = async (key: string, question: string) => {
    if (answerMap[key]) {
      setAnswerMap((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      return;
    }
    if (answerLoading) return;
    setAnswerLoading(key);
    setAnswerError("");
    try {
      const answer = await generateQuestionAnswer({
        question,
        job_id: jobId ?? null,
        resume_id: resumeId ?? null,
      });
      setAnswerMap((current) => ({ ...current, [key]: answer }));
    } catch (err) {
      setAnswerError(err instanceof Error ? err.message : "生成参考答案失败");
    } finally {
      setAnswerLoading(null);
    }
  };

  const total = data?.groups.reduce((sum, group) => sum + group.questions.length, 0) ?? 0;
  const historyItems = (banks.data ?? []).map((bank) => ({
    key: String(bank.id),
    label: (
      <Space wrap>
        <span>{bank.resume_title || bank.job_title || "题库"}</span>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {bank.created_at.replace("T", " ").slice(0, 16)}
        </Typography.Text>
      </Space>
    ),
    children: (
      <Space direction="vertical" style={{ width: "100%" }}>
        {bank.groups.map((group) => (
          <div key={group.type}>
            <Typography.Text strong>{group.type}</Typography.Text>
            <ul style={{ paddingLeft: 20, margin: "4px 0" }}>
              {group.questions.map((item) => (
                <li key={item.question}>{item.question}</li>
              ))}
            </ul>
          </div>
        ))}
        <Popconfirm
          title="删除这条题库历史？"
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true, "aria-label": `确认删除题库历史 ${bank.id}` }}
          onConfirm={() => void removeBank(bank.id)}
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
      <Card size="small" title="个性化题库">
        <Space wrap>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            style={{ minWidth: 240 }}
            placeholder="关联岗位（选填）"
            value={jobId}
            onChange={setJobId}
            options={jobOptions}
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            style={{ minWidth: 240 }}
            placeholder="关联简历（选填）"
            value={resumeId}
            onChange={setResumeId}
            options={resumeOptions}
          />
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={loading}
            onClick={() => void generate()}
          >
            生成题库
          </Button>
          {data && (
            <>
              <Button
                icon={<PlayCircleOutlined />}
                disabled={total === 0}
                onClick={startSession}
              >
                开始模拟面试
              </Button>
              <Button icon={<SaveOutlined />} loading={saving} onClick={() => void saveBank()}>
                保存题库
              </Button>
            </>
          )}
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          题库基于岗位 JD、简历与已确认的事实台账即时生成，覆盖基础题、项目深挖题与反问 HR 题三类。
        </Typography.Paragraph>
      </Card>

      {loading ? (
        <Spin />
      ) : error ? (
        <Alert type="error" showIcon message={error} />
      ) : !data ? (
        <Empty description="选择岗位或简历后生成题库" />
      ) : (
        <>
          {data.notes.map((note) => (
            <Alert key={note} type="warning" showIcon message={note} />
          ))}
          {answerError && <Alert type="error" showIcon message={answerError} />}
          <Space wrap>
            <Typography.Text strong>共 {total} 题</Typography.Text>
            {data.groups.map((group) =>
              group.questions.length ? (
                <Tag key={group.type} color="geekblue">
                  {group.type} {group.questions.length}
                </Tag>
              ) : null,
            )}
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void generate()}>
              重新生成
            </Button>
          </Space>
          {QUESTION_BANK_TYPES.map((type) => {
            const group = data.groups.find((item) => item.type === type);
            if (!group || group.questions.length === 0) return null;
            return (
              <Card key={type} size="small" title={type}>
                <Space direction="vertical" style={{ width: "100%" }} size="small">
                  {group.questions.map((item, index) => {
                    const key = `${group.type}-${index}`;
                    const answer = answerMap[key];
                    return (
                      <div
                        key={key}
                        style={{
                          borderTop: index ? "1px solid #f0f0f0" : "none",
                          paddingTop: index ? 8 : 0,
                        }}
                      >
                        <Typography.Text strong>
                          {index + 1}. {item.question}
                        </Typography.Text>
                        {item.purpose && (
                          <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0" }}>
                            考察：{item.purpose}
                          </Typography.Paragraph>
                        )}
                        {item.answer_hint && (
                          <Typography.Paragraph style={{ margin: "4px 0 0" }}>
                            <Typography.Text type="success">提示：</Typography.Text>
                            {item.answer_hint}
                          </Typography.Paragraph>
                        )}
                        <div style={{ marginTop: 4 }}>
                          <Button
                            size="small"
                            type="link"
                            icon={<BulbOutlined />}
                            loading={answerLoading === key}
                            onClick={() => void toggleAnswer(key, item.question)}
                          >
                            {answer ? "收起参考答案" : "参考答案"}
                          </Button>
                        </div>
                        {answer && (
                          <div style={{ marginTop: 4 }}>
                            <Typography.Paragraph style={{ margin: "4px 0 0", whiteSpace: "pre-wrap" }}>
                              {answer.answer}
                            </Typography.Paragraph>
                            {answer.key_points.length > 0 && (
                              <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                                {answer.key_points.map((point) => (
                                  <li key={point}>{point}</li>
                                ))}
                              </ul>
                            )}
                            {answer.sample_phrasing && (
                              <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0" }}>
                                话术参考：{answer.sample_phrasing}
                              </Typography.Paragraph>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </Space>
              </Card>
            );
          })}
        </>
      )}

      <Card
        size="small"
        title={
          <Space>
            <HistoryOutlined />
            历史题库
          </Space>
        }
      >
        {banks.loading && !banks.data ? (
          <Spin />
        ) : banks.error ? (
          <Alert type="error" showIcon message={banks.error} />
        ) : (banks.data ?? []).length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有保存过题库" />
        ) : (
          <Collapse items={historyItems} />
        )}
      </Card>
    </Space>
  );
}
