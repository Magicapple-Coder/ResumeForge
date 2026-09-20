/**
 * 模拟面试：设定面试官 → 逐轮问答 → 结束后看评分报告。
 *
 * 与求职助手的差别：这里**流程由代码控制**（轮数、何时结束、什么时候出报告），所以界面上
 * 会明确显示"第 N/6 轮"，用户始终知道还剩几个问题；助手那边则是自由对话。
 */
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Progress,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createInterview,
  deleteInterview,
  finishInterview,
  getInterview,
  interviewToMaterial,
  listInterviews,
  submitInterviewAnswer,
} from "../api/interview";
import { listJobs } from "../api/jobs";
import { listResumes } from "../api/resumes";
import InterviewExperiencePanel from "../components/InterviewExperiencePanel";
import InterviewReviewPanel from "../components/InterviewReviewPanel";
import QuestionBankPanel from "../components/QuestionBankPanel";
import { RowActions } from "../components/common/RowActions";
import type {
  InterviewBrief,
  InterviewDetail,
  InterviewDifficulty,
  InterviewReviewRecord,
  InterviewType,
  InterviewerStyle,
  QuestionBankRecord,
} from "../types";
import {
  INTERVIEW_DIFFICULTIES,
  INTERVIEW_TYPES,
  INTERVIEWER_STYLES,
  MAX_INTERVIEW_ROUNDS,
  MIN_INTERVIEW_ROUNDS,
} from "../types";
import { formatDateTime } from "../utils/format";

const CONFIDENCE_TIP =
  "面试官会基于你的资料与岗位要求提问，回答越具体（做了什么、结果是什么）点评越有用。";

interface SetupForm {
  jobId?: number;
  interviewType: InterviewType;
  difficulty: InterviewDifficulty;
  interviewerStyle: InterviewerStyle;
  rounds: number;
  focus: string;
  persona: string;
}

function ReportCard({
  session,
  onSaveToMaterial,
  saving,
}: {
  session: InterviewDetail;
  onSaveToMaterial: () => void;
  saving: boolean;
}) {
  const report = session.report ?? {};
  const failed = report.error || (!report.dimensions?.length && !report.summary);
  return (
    <Card size="small" className="interview-report" title="面试评分报告">
      {failed ? (
        <Alert
          type="warning"
          showIcon
          message="报告没有生成成功"
          description={
            report.summary || "可以在资料箱里找到这场面试的问答记录，重新体验一次也可以。"
          }
        />
      ) : (
        <>
          <div className="interview-report-score">
            <Progress
              type="dashboard"
              size={120}
              percent={Math.round(report.score ?? 0)}
              format={(value) => `${value} 分`}
            />
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              {report.summary}
            </Typography.Paragraph>
          </div>
          <List
            size="small"
            dataSource={report.dimensions ?? []}
            renderItem={(item) => (
              <List.Item>
                <div className="interview-dimension">
                  <div className="interview-dimension-head">
                    <b>{item.name}</b>
                    <Tag color={item.score >= 80 ? "green" : item.score >= 60 ? "gold" : "red"}>
                      {item.score} 分
                    </Tag>
                  </div>
                  <Typography.Text type="secondary">{item.comment}</Typography.Text>
                </div>
              </List.Item>
            )}
          />
          <div className="interview-report-lists">
            <div>
              <Typography.Title level={5}>做得好的地方</Typography.Title>
              <ul>
                {(report.strengths ?? []).map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </div>
            <div>
              <Typography.Title level={5}>下次可以改进</Typography.Title>
              <ul>
                {(report.improvements ?? []).map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
      <Button onClick={onSaveToMaterial} loading={saving} icon={<PlusOutlined />}>
        把这场面试存进资料箱
      </Button>
    </Card>
  );
}

export default function InterviewPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<InterviewBrief[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [active, setActive] = useState<InterviewDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [answer, setAnswer] = useState("");
  const [savingReport, setSavingReport] = useState(false);
  const [jobOptions, setJobOptions] = useState<{ value: number; label: string }[]>([]);
  const [resumeOptions, setResumeOptions] = useState<{ value: number; label: string }[]>([]);
  const [activeTab, setActiveTab] = useState("session");
  const [form] = Form.useForm<SetupForm>();
  const endRef = useRef<HTMLDivElement>(null);
  // 历史记录富还原：从「历史题库 / 历史复盘」打开某条记录后，把它传给面板用相同渲染路径展示。
  const [bankRecord, setBankRecord] = useState<QuestionBankRecord | null>(null);
  const [reviewRecord, setReviewRecord] = useState<InterviewReviewRecord | null>(null);

  const loadList = useCallback(async () => {
    setLoadingList(true);
    try {
      setSessions(await listInterviews());
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取面试记录失败");
    } finally {
      setLoadingList(false);
    }
  }, [message]);

  useEffect(() => {
    void loadList();
    listJobs({ page_size: 100 })
      .then((page) =>
        setJobOptions(
          page.items.map((job) => ({
            value: job.id,
            label: `${job.title}${job.company ? ` · ${job.company}` : ""}`,
          })),
        ),
      )
      .catch(() => setJobOptions([]));
    listResumes({ page_size: 100 })
      .then((page) =>
        setResumeOptions(
          page.items.map((resume) => ({
            value: resume.id,
            label: resume.title || `简历 #${resume.id}`,
          })),
        ),
      )
      .catch(() => setResumeOptions([]));
  }, [loadList]);

  // 新消息进来后滚到底部，用户不用自己找。
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [active?.messages.length, submitting]);

  const start = async (values: SetupForm) => {
    setStarting(true);
    try {
      const session = await createInterview({
        job_id: values.jobId ?? null,
        interview_type: values.interviewType,
        difficulty: values.difficulty,
        interviewer_style: values.interviewerStyle,
        rounds: values.rounds,
        focus: values.focus ?? "",
        persona: values.persona ?? "",
      });
      setActive(session);
      setAnswer("");
      await loadList();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "开始面试失败");
    } finally {
      setStarting(false);
    }
  };

  const openSession = async (id: number) => {
    try {
      setActive(await getInterview(id));
      setAnswer("");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "打开面试失败");
    }
  };

  const sendAnswer = async () => {
    if (!active || !answer.trim() || submitting) return;
    setSubmitting(true);
    const content = answer.trim();
    setAnswer("");
    try {
      const result = await submitInterviewAnswer(active.id, content);
      setActive(result.session);
      if (result.finished) {
        message.success("面试结束，评分报告已生成");
        await loadList();
      }
    } catch (error) {
      // 回答已经写到服务端了（后端先存后问），所以失败时提示"重试"而不是"重写"。
      message.error(error instanceof Error ? error.message : "提交回答失败，请重试");
      setAnswer(content);
    } finally {
      setSubmitting(false);
    }
  };

  const endEarly = () => {
    if (!active) return;
    Modal.confirm({
      title: "结束这场面试？",
      content: "结束后会根据已有的问答生成评分报告，不能再补充回答。",
      okText: "结束并出报告",
      cancelText: "继续面试",
      onOk: async () => {
        setSubmitting(true);
        try {
          setActive(await finishInterview(active.id));
          message.success("面试已结束");
          await loadList();
        } catch (error) {
          message.error(error instanceof Error ? error.message : "结束面试失败");
        } finally {
          setSubmitting(false);
        }
      },
    });
  };

  const remove = async (session: InterviewBrief) => {
    try {
      await deleteInterview(session.id);
      if (active?.id === session.id) setActive(null);
      message.success("已删除这场面试");
      await loadList();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const saveReport = async () => {
    if (!active) return;
    setSavingReport(true);
    try {
      await interviewToMaterial(active.id);
      message.success("已存进资料箱的「面试复盘」分类");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "存进资料箱失败");
    } finally {
      setSavingReport(false);
    }
  };

  // 题库「开始模拟面试」：把题目带入面试的考察重点，并切回模拟面试页。
  const startFromBank = (questions: string[]) => {
    const focus = questions.slice(0, 6).join("；").slice(0, 255);
    form.setFieldsValue({ focus });
    setActiveTab("session");
    message.info("题目已带入「考察重点」，调整后即可开始面试");
  };

  const answered = active?.answered_rounds ?? 0;
  const finished = active?.status === "finished";

  return (
    <div className="interview-page">
      <div className="profile-page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            模拟面试
          </Typography.Title>
          <Typography.Text type="secondary">
            让 AI 面试官按你设定的类型与难度提问，结束后给出评分报告与改进建议。
          </Typography.Text>
        </div>
        {active && (
          <Button icon={<ArrowLeftOutlined />} onClick={() => setActive(null)}>
            回到设置
          </Button>
        )}
      </div>

      {!active ? (
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "session",
              label: "模拟面试",
              children: (
                <div className="interview-setup">
                  <Card size="small" className="settings-card">
                    <Typography.Title level={5} style={{ marginTop: 0 }}>
                      面试官设定
                    </Typography.Title>
                    <Form
                      form={form}
                      layout="vertical"
                      initialValues={{
                        interviewType: "技术面",
                        difficulty: "中级",
                        interviewerStyle: "严谨专业",
                        rounds: 6,
                        focus: "",
                        persona: "",
                      }}
                      onFinish={(values) => void start(values)}
                    >
                      <div className="interview-setup-grid">
                        <Form.Item label="关联岗位（选填）" name="jobId">
                          <Select
                            allowClear
                            showSearch
                            optionFilterProp="label"
                            placeholder="选中后按该岗位的 JD 提问"
                            options={jobOptions}
                          />
                        </Form.Item>
                        <Form.Item label="面试类型" name="interviewType">
                          <Select
                            options={INTERVIEW_TYPES.map((value) => ({ value, label: value }))}
                          />
                        </Form.Item>
                        <Form.Item label="难度" name="difficulty">
                          <Select
                            options={INTERVIEW_DIFFICULTIES.map((value) => ({
                              value,
                              label: value,
                            }))}
                          />
                        </Form.Item>
                        <Form.Item label="面试官风格" name="interviewerStyle">
                          <Select
                            options={INTERVIEWER_STYLES.map((value) => ({ value, label: value }))}
                          />
                        </Form.Item>
                        <Form.Item
                          label="轮数"
                          name="rounds"
                          extra={`${MIN_INTERVIEW_ROUNDS}-${MAX_INTERVIEW_ROUNDS} 轮`}
                        >
                          <InputNumber
                            min={MIN_INTERVIEW_ROUNDS}
                            max={MAX_INTERVIEW_ROUNDS}
                            style={{ width: "100%" }}
                          />
                        </Form.Item>
                        <Form.Item
                          label="考察重点（选填）"
                          name="focus"
                          extra="例如：Go 并发、分布式、项目取舍"
                        >
                          <Input maxLength={255} placeholder="留空则按面试类型通用考察" />
                        </Form.Item>
                      </div>
                      <Form.Item
                        label="自定义面试官人设（选填）"
                        name="persona"
                        extra="例如：某大厂后端团队负责人，喜欢追问性能指标与故障处理细节。优先级高于上面的默认风格。"
                      >
                        <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} maxLength={2000} />
                      </Form.Item>
                      <Space wrap>
                        <Button
                          type="primary"
                          htmlType="submit"
                          icon={<PlayCircleOutlined />}
                          loading={starting}
                        >
                          开始面试
                        </Button>
                        <Typography.Text type="secondary">{CONFIDENCE_TIP}</Typography.Text>
                      </Space>
                    </Form>
                  </Card>

                  <Card
                    size="small"
                    className="settings-card"
                    title="历史面试"
                    style={{ marginTop: 16 }}
                  >
                    {loadingList ? (
                      <Spin />
                    ) : sessions.length === 0 ? (
                      <Empty description="还没有做过模拟面试" />
                    ) : (
                      <List
                        size="small"
                        dataSource={sessions}
                        renderItem={(item) => (
                          <List.Item
                            actions={[
                              <RowActions
                                key="actions"
                                primary={[
                                  {
                                    key: "open",
                                    label: item.status === "active" ? "继续" : "看报告",
                                    onClick: () => void openSession(item.id),
                                  },
                                ]}
                                more={[
                                  {
                                    key: "delete",
                                    label: "删除这场面试",
                                    danger: true,
                                    icon: <DeleteOutlined />,
                                    confirm: "删除这场面试？删除后可在回收站找回。",
                                    onClick: () => void remove(item),
                                  },
                                ]}
                              />,
                            ]}
                          >
                            <List.Item.Meta
                              title={
                                <Space size={6} wrap>
                                  <span>{item.title}</span>
                                  <Tag color={item.status === "active" ? "blue" : "default"}>
                                    {item.status === "active" ? "进行中" : "已结束"}
                                  </Tag>
                                  <Tag>{item.interview_type}</Tag>
                                  <Tag>{item.difficulty}</Tag>
                                </Space>
                              }
                              description={`第 ${item.answered_rounds}/${item.rounds} 轮 · ${formatDateTime(item.created_at)}`}
                            />
                          </List.Item>
                        )}
                      />
                    )}
                  </Card>
                </div>
              ),
            },
            {
              key: "bank",
              label: "题库",
              children: (
                <QuestionBankPanel
                  jobOptions={jobOptions}
                  resumeOptions={resumeOptions}
                  onStartSession={startFromBank}
                  record={bankRecord}
                  onOpenRecord={setBankRecord}
                  onCloseRecord={() => setBankRecord(null)}
                />
              ),
            },
            {
              key: "experiences",
              label: "面经",
              children: <InterviewExperiencePanel jobOptions={jobOptions} />,
            },
            {
              key: "review",
              label: "面试复盘",
              children: (
                <InterviewReviewPanel
                  jobOptions={jobOptions}
                  resumeOptions={resumeOptions}
                  onGoToResume={() => navigate("/resumes")}
                  record={reviewRecord}
                  onOpenRecord={setReviewRecord}
                  onCloseRecord={() => setReviewRecord(null)}
                />
              ),
            },
          ]}
        />
      ) : (
        <div className="interview-room">
          <div className="interview-room-head">
            <Space size={6} wrap>
              <b>{active.title}</b>
              <Tag color="blue">{active.interview_type}</Tag>
              <Tag>{active.difficulty}</Tag>
              <Tag>{active.interviewer_style}</Tag>
              {active.job_title ? <Tag color="geekblue">{active.job_title}</Tag> : null}
            </Space>
            <Space size={6} wrap>
              <Typography.Text type="secondary">
                第 {Math.min(answered + (finished ? 0 : 1), active.rounds)} / {active.rounds} 轮
              </Typography.Text>
              {!finished && (
                <Button
                  size="small"
                  danger
                  icon={<StopOutlined />}
                  onClick={endEarly}
                  loading={submitting}
                >
                  结束并出报告
                </Button>
              )}
              <Button size="small" icon={<ThunderboltOutlined />} onClick={() => setActive(null)}>
                新开一场
              </Button>
            </Space>
          </div>

          <div className="interview-messages">
            {active.messages.map((item) =>
              item.role === "note" ? (
                <div key={item.id} className="interview-note">
                  {item.content}
                </div>
              ) : (
                <div
                  key={item.id}
                  className={`interview-message interview-message--${item.role === "interviewer" ? "interviewer" : "me"}`}
                >
                  <div className="interview-message-head">
                    <b>{item.role === "interviewer" ? "面试官" : "我"}</b>
                    <Typography.Text type="secondary" className="assistant-message-time">
                      {formatDateTime(item.created_at)}
                    </Typography.Text>
                  </div>
                  <div className="interview-message-body">{item.content}</div>
                  {item.context.feedback ? (
                    <div className="interview-feedback">
                      <b>面试官点评：</b>
                      {item.context.feedback}
                    </div>
                  ) : null}
                </div>
              ),
            )}
            {submitting && !finished ? (
              <div className="interview-message interview-message--interviewer">
                <div className="interview-message-body">
                  <Spin size="small" /> 面试官正在思考下一个问题…
                </div>
              </div>
            ) : null}
            <div ref={endRef} />
          </div>

          {finished ? (
            <ReportCard
              session={active}
              onSaveToMaterial={() => void saveReport()}
              saving={savingReport}
            />
          ) : (
            <div className="interview-composer">
              <Input.TextArea
                value={answer}
                autoSize={{ minRows: 3, maxRows: 10 }}
                placeholder="像真实面试那样回答：先说结论，再说做了什么、结果如何（Ctrl+Enter 发送）"
                disabled={submitting}
                onChange={(event) => setAnswer(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                    event.preventDefault();
                    void sendAnswer();
                  }
                }}
              />
              <div className="interview-composer-actions">
                <Typography.Text type="secondary">
                  答不上来可以直接说「不知道」，面试官会给回答思路。
                </Typography.Text>
                <Button
                  type="primary"
                  loading={submitting}
                  disabled={!answer.trim()}
                  onClick={() => void sendAnswer()}
                >
                  提交回答
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
