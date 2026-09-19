/** 首页：数据概览、"接下来做什么"、全局搜索与最近动态。 */
import {
  AuditOutlined,
  BarChartOutlined,
  CalendarOutlined,
  FileTextOutlined,
  FunnelPlotOutlined,
  InboxOutlined,
  RocketOutlined,
  SearchOutlined,
  SendOutlined,
  SolutionOutlined,
  StarOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Modal,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createSearchParams, Link } from "react-router-dom";
import { listUpcomingReminders } from "../api/reminders";
import { getStats, searchAll } from "../api/search";
import { getReminderPopupSetting } from "../api/settings";
import { useApi } from "../hooks/useApi";
import { REMINDER_URGENCY_COLORS } from "../types";
import type { ReminderUpcoming, SearchHitType, SearchResult } from "../types";
import { formatDateTime } from "../utils/format";

/** 快捷入口：点一下就到自己要做的那件事上，不用先想它在哪个菜单里。 */
const SHORTCUTS = [
  {
    path: "/analytics",
    icon: <BarChartOutlined />,
    label: "求职统计",
    hint: "投递漏斗与月度趋势",
  },
  {
    path: "/interview",
    icon: <SolutionOutlined />,
    label: "模拟面试·题库",
    hint: "对话练习与即时出题",
  },
  {
    path: "/apply",
    icon: <TeamOutlined />,
    label: "内推管理",
    hint: "找人内推，记录每一次进展",
  },
  {
    path: "/tracker",
    icon: <CalendarOutlined />,
    label: "日历提醒",
    hint: "面试、测评截止别错过",
  },
] as const;

/** 全局搜索"更多结果"分组的展示顺序与图标/标签（与后端下发顺序一致）。 */
const MORE_ORDER: SearchHitType[] = [
  "referral",
  "reminder",
  "experience",
  "claim",
  "material",
  "skill",
];

const MORE_HIT_META: Record<SearchHitType, { icon: ReactNode; label: string }> = {
  referral: { icon: <TeamOutlined />, label: "内推" },
  reminder: { icon: <CalendarOutlined />, label: "提醒" },
  experience: { icon: <SolutionOutlined />, label: "面经" },
  claim: { icon: <AuditOutlined />, label: "事实台账" },
  material: { icon: <InboxOutlined />, label: "资料" },
  skill: { icon: <ToolOutlined />, label: "技能" },
};

export default function HomePage() {
  const { data: stats, loading, error: statsError } = useApi(getStats);
  const { data: upcomingReminders, loading: remindersLoading } = useApi(
    () => listUpcomingReminders(8),
    [],
  );
  const { data: popupSetting } = useApi(getReminderPopupSetting, []);
  const [popupVisible, setPopupVisible] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [resultKeyword, setResultKeyword] = useState("");
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState("");
  const searchVersion = useRef(0);

  // 打开应用时：设置开启且有未完成提醒 → 弹出近期提醒。
  useEffect(() => {
    if (popupSetting?.enabled && (upcomingReminders?.length ?? 0) > 0) {
      setPopupVisible(true);
    }
  }, [popupSetting, upcomingReminders]);

  useEffect(
    () => () => {
      searchVersion.current += 1;
    },
    [],
  );

  const onSearch = async (value: string) => {
    const keyword = value.trim();
    const currentSearch = ++searchVersion.current;
    if (!keyword) {
      setSearching(false);
      setSearched(false);
      setResult(null);
      setResultKeyword("");
      setSearchError("");
      return;
    }
    setSearching(true);
    setSearched(true);
    setResult(null);
    setSearchError("");
    try {
      const nextResult = await searchAll(keyword);
      if (currentSearch === searchVersion.current) {
        setResult(nextResult);
        setResultKeyword(keyword);
      }
    } catch (error) {
      if (currentSearch === searchVersion.current) {
        setResult(null);
        setSearchError(error instanceof Error ? error.message : "搜索失败，请重试");
      }
    } finally {
      if (currentSearch === searchVersion.current) setSearching(false);
    }
  };

  // "接下来做什么"只列**待办**，不列"你已经做了多少"——概览页上能推动人的只有前者。
  // 每一条都带数字与去处，点进去就是那件事本身。
  const todos = [
    stats?.pending_claim_count
      ? {
          key: "claims",
          icon: <AuditOutlined />,
          text: `有 ${stats.pending_claim_count} 条事实还没核实`,
          hint: "没核实的主张不能进正式简历，导出时会被拦下",
          path: "/claims",
        }
      : null,
    stats?.apply_queue_count
      ? {
          key: "queue",
          icon: <SendOutlined />,
          text: `投递队列里有 ${stats.apply_queue_count} 个岗位在等`,
          hint: "排好队、启动浏览器就能投",
          path: "/apply",
        }
      : null,
    stats?.stalled_application_count
      ? {
          key: "stalled",
          icon: <FunnelPlotOutlined />,
          text: `有 ${stats.stalled_application_count} 条投递超过一周没更新`,
          hint: "去看看要不要补一句跟进或改状态",
          path: "/tracker",
        }
      : null,
  ].filter((item) => item !== null);

  return (
    <div>
      {statsError && (
        <Alert type="error" showIcon message={statsError} style={{ marginBottom: 16 }} />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={loading}>
            <Statistic title="岗位总数" value={stats?.job_count ?? 0} prefix={<SearchOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={loading}>
            <Statistic
              title="开放中岗位"
              value={stats?.open_job_count ?? 0}
              prefix={<RocketOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={loading}>
            <Statistic
              title="已生成简历"
              value={stats?.resume_count ?? 0}
              prefix={<FileTextOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={loading}>
            <Statistic
              title="近 7 天生成"
              value={stats?.week_resume_count ?? 0}
              prefix={<StarOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card
        style={{ marginTop: 16 }}
        title={
          <Space size={8}>
            <CalendarOutlined />
            <span>近期提醒</span>
          </Space>
        }
        extra={<Link to="/tracker">查看全部</Link>}
        loading={remindersLoading}
      >
        {(upcomingReminders ?? []).length === 0 ? (
          <Empty description="近期没有待办提醒" />
        ) : (
          <List
            size="small"
            dataSource={upcomingReminders ?? []}
            renderItem={(item: ReminderUpcoming) => (
              <List.Item>
                <Space size={6} wrap>
                  <Tag color={REMINDER_URGENCY_COLORS[item.urgency] ?? "default"}>
                    {item.due_label}
                  </Tag>
                  <Link to="/tracker">{item.title}</Link>
                  <Typography.Text type="secondary">
                    {formatDateTime(item.remind_at)}
                  </Typography.Text>
                </Space>
              </List.Item>
            )}
          />
        )}
      </Card>

      <Card
        style={{ marginTop: 16 }}
        title={
          <Space size={8}>
            <ThunderboltOutlined />
            <span>接下来做什么</span>
          </Space>
        }
      >
        {loading ? (
          <Typography.Text type="secondary">正在读取…</Typography.Text>
        ) : todos.length > 0 ? (
          <ul className="home-todo-list">
            {todos.map((todo) => (
              <li key={todo.key} className="home-todo-item">
                <span className="home-todo-icon">{todo.icon}</span>
                <span className="home-todo-copy">
                  <Link to={todo.path} className="home-todo-text">
                    {todo.text}
                  </Link>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {todo.hint}
                  </Typography.Text>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <Typography.Text type="secondary">
            眼下没有待办。可以去「岗位广场」收几个岗位，或到「求职助手」聊聊下一步。
          </Typography.Text>
        )}
      </Card>

      <Card style={{ marginTop: 16 }} title="快捷入口">
        <div className="home-shortcuts">
          {SHORTCUTS.map((item) => (
            <Link key={item.path} to={item.path} className="home-shortcut">
              <span className="home-shortcut-icon">{item.icon}</span>
              <span className="home-shortcut-label">{item.label}</span>
              <span className="home-shortcut-hint">{item.hint}</span>
            </Link>
          ))}
        </div>
      </Card>

      <Card style={{ marginTop: 16 }}>
        <Typography.Title level={5}>全局搜索</Typography.Title>
        <Input.Search
          placeholder="搜索岗位、简历，或内推、提醒、面经、台账、资料、技能，如：后端开发 / 字节跳动"
          enterButton="搜索"
          size="large"
          loading={searching}
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          onSearch={(value) => void onSearch(value)}
        />
        {searchError && (
          <Alert type="error" showIcon message={searchError} style={{ marginTop: 16 }} />
        )}
        {searched && (
          <div className="home-search-results">
            <Typography.Title level={5} type="secondary" style={{ margin: "8px 0" }}>
              匹配的岗位（{result?.jobs.length ?? 0}）
            </Typography.Title>
            <List
              size="small"
              dataSource={result?.jobs ?? []}
              locale={{ emptyText: <Empty description="没有匹配的岗位" /> }}
              renderItem={(job) => (
                <List.Item>
                  <Space>
                    <Link to={`/jobs?${createSearchParams({ keyword: resultKeyword })}`}>
                      {job.title}
                    </Link>
                    <Tag>{job.company}</Tag>
                    <Tag color="blue">{job.location}</Tag>
                    <Typography.Text type="secondary">{job.salary || "薪资面议"}</Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
            <Typography.Title level={5} type="secondary" style={{ margin: "8px 0" }}>
              匹配的简历记录（{result?.resumes.length ?? 0}）
            </Typography.Title>
            <List
              size="small"
              dataSource={result?.resumes ?? []}
              locale={{ emptyText: <Empty description="没有匹配的简历记录" /> }}
              renderItem={(resume) => (
                <List.Item>
                  <Space>
                    <Link to="/resumes">{resume.title}</Link>
                    <Tag>{resume.job_title}</Tag>
                    <Typography.Text type="secondary">
                      {formatDateTime(resume.created_at)}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
            {(result?.more.length ?? 0) > 0 && (
              <div style={{ marginTop: 8 }}>
                <Typography.Title level={5} type="secondary" style={{ margin: "8px 0" }}>
                  更多结果（{result?.more.length ?? 0}）
                </Typography.Title>
                {MORE_ORDER.map((type) => {
                  const hits = (result?.more ?? []).filter((hit) => hit.type === type);
                  if (hits.length === 0) return null;
                  const meta = MORE_HIT_META[type];
                  return (
                    <div key={type} className="home-more-group">
                      <Space size={6} className="home-more-heading">
                        {meta.icon}
                        <Typography.Text type="secondary">
                          {meta.label}（{hits.length}）
                        </Typography.Text>
                      </Space>
                      <List
                        size="small"
                        dataSource={hits}
                        renderItem={(hit) => (
                          <List.Item>
                            <Space>
                              <Link to={hit.path}>{hit.title}</Link>
                              {hit.subtitle && (
                                <Typography.Text type="secondary">{hit.subtitle}</Typography.Text>
                              )}
                            </Space>
                          </List.Item>
                        )}
                      />
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </Card>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="最近岗位" extra={<Link to="/jobs">查看全部</Link>}>
            <List
              size="small"
              dataSource={stats?.latest_jobs ?? []}
              locale={{ emptyText: <Empty description="暂无岗位，去「岗位广场」手动添加" /> }}
              renderItem={(job) => (
                <List.Item>
                  <Space>
                    <Link to="/jobs">{job.title}</Link>
                    <Tag>{job.company}</Tag>
                    <Typography.Text type="secondary">
                      {formatDateTime(job.created_at)}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="最近生成的简历" extra={<Link to="/resumes">查看全部</Link>}>
            <List
              size="small"
              dataSource={stats?.latest_resumes ?? []}
              locale={{
                emptyText: <Empty description="暂无简历记录，去「岗位广场」选个岗位试试" />,
              }}
              renderItem={(resume) => (
                <List.Item>
                  <Space>
                    <Link to="/resumes">{resume.title}</Link>
                    <Typography.Text type="secondary">
                      {formatDateTime(resume.created_at)}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      {(stats?.latest_applications.length ?? 0) > 0 && (
        <Card
          style={{ marginTop: 16 }}
          title="最近投出去的"
          extra={<Link to="/tracker">看进度</Link>}
        >
          <List
            size="small"
            dataSource={stats?.latest_applications ?? []}
            renderItem={(item) => (
              <List.Item>
                <Space>
                  <Link to="/tracker">{item.job_title || "未命名岗位"}</Link>
                  <Tag>{item.company}</Tag>
                  <Typography.Text type="secondary">
                    {formatDateTime(item.updated_at)}
                  </Typography.Text>
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}

      <Modal
        open={popupVisible}
        title="近期提醒"
        onCancel={() => setPopupVisible(false)}
        footer={
          <Button type="primary" onClick={() => setPopupVisible(false)}>
            知道了
          </Button>
        }
      >
        <List
          size="small"
          dataSource={upcomingReminders ?? []}
          renderItem={(item: ReminderUpcoming) => (
            <List.Item>
              <Space size={6} wrap>
                <Tag color={REMINDER_URGENCY_COLORS[item.urgency] ?? "default"}>
                  {item.due_label}
                </Tag>
                <Link to="/tracker" onClick={() => setPopupVisible(false)}>
                  {item.title}
                </Link>
                <Typography.Text type="secondary">
                  {formatDateTime(item.remind_at)}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      </Modal>
    </div>
  );
}
