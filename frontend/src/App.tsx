import {
  AuditOutlined,
  BarChartOutlined,
  BookOutlined,
  DeleteOutlined,
  FileTextOutlined,
  FunnelPlotOutlined,
  GithubOutlined,
  HomeOutlined,
  InboxOutlined,
  MessageOutlined,
  ProfileOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  SendOutlined,
  SettingOutlined,
  SolutionOutlined,
  StarOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Skeleton, Tooltip, Typography } from "antd";
import { lazy, Suspense, useEffect, useState } from "react";
import { Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import AppHeaderContext from "./components/AppHeaderContext";
import BackgroundTasksIndicator from "./components/BackgroundTasksIndicator";
import ExitAppButton from "./components/common/ExitAppButton";
import TaskCompletionNotifier from "./components/TaskCompletionNotifier";
import UpdateCheckButton from "./components/UpdateCheckButton";
import { APP_NAME, GITHUB_REPO } from "./config";
import { consumeFirstVisitGuide } from "./utils/userGuide";
// 侧栏品牌图标。走 import 而不是写死 "/resumeforge-icon.png"——Vite 会按 `base`
// 重写成正确前缀（在线体验产物部署在 Pages 子路径下，写死绝对路径会 404）。
// 特意用 src/assets/ 的副本而不是 public/ 下的同名文件：引用 public/ 里的资源不会
// 经过 Vite 的 base 重写，等于没修。
import brandIcon from "./assets/resumeforge-icon.png";

const HomePage = lazy(() => import("./pages/HomePage"));
const JobsPage = lazy(() => import("./pages/JobsPage"));
const ProfilePage = lazy(() => import("./pages/ProfilePage"));
const ClaimsPage = lazy(() => import("./pages/ClaimsPage"));
const DrillPage = lazy(() => import("./pages/DrillPage"));
const ResumesPage = lazy(() => import("./pages/ResumesPage"));
const ApplyPage = lazy(() => import("./pages/ApplyPage"));
const TrackerPage = lazy(() => import("./pages/TrackerPage"));
const FavoritesPage = lazy(() => import("./pages/FavoritesPage"));
const AssistantPage = lazy(() => import("./pages/AssistantPage"));
const MaterialsPage = lazy(() => import("./pages/MaterialsPage"));
const KnowledgePage = lazy(() => import("./pages/KnowledgePage"));
const SkillsPage = lazy(() => import("./pages/SkillsPage"));
const InterviewPage = lazy(() => import("./pages/InterviewPage"));
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const TrashPage = lazy(() => import("./pages/TrashPage"));
const UserGuideModal = lazy(() => import("./components/UserGuideModal"));

const { Sider, Header, Content } = Layout;

/**
 * 侧栏导航按「找岗位 → 做简历 → 投递跟进 → 面试准备 → 我的数据 → 系统」的顺序分组。
 *
 * 分组依据是用户真实的使用顺序，而不是功能上线时间：收藏夹紧跟岗位广场（同属"找岗位"），
 * 「我的资料」排在资料箱/工作台之前（它是后面几项的数据来源），「事实台账」靠近设置
 * （属于数据核对一类的低频入口）。**顺序即分组，不额外加分隔标题**——侧栏只有 200px，
 * 加分组标题会把 13 项挤成两屏。
 */
export const MENU_ITEMS = [
  // 找岗位
  { key: "/", icon: <HomeOutlined />, label: "首页" },
  { key: "/jobs", icon: <SearchOutlined />, label: "岗位广场" },
  { key: "/favorites", icon: <StarOutlined />, label: "收藏夹" },
  // 做简历
  { key: "/resumes", icon: <FileTextOutlined />, label: "简历中心" },
  // 投递与跟进
  { key: "/apply", icon: <SendOutlined />, label: "投递台" },
  { key: "/tracker", icon: <FunnelPlotOutlined />, label: "求职进度" },
  { key: "/analytics", icon: <BarChartOutlined />, label: "求职统计" },
  // 面试准备
  { key: "/interview", icon: <SolutionOutlined />, label: "模拟面试" },
  { key: "/assistant", icon: <MessageOutlined />, label: "求职助手" },
  // 我的数据
  { key: "/profile", icon: <ProfileOutlined />, label: "我的资料" },
  { key: "/materials", icon: <InboxOutlined />, label: "资料箱" },
  { key: "/knowledge", icon: <BookOutlined />, label: "知识库" },
  { key: "/skills", icon: <ToolOutlined />, label: "工作台" },
  // 系统
  { key: "/claims", icon: <AuditOutlined />, label: "事实台账" },
  { key: "/trash", icon: <DeleteOutlined />, label: "回收站" },
  { key: "/settings", icon: <SettingOutlined />, label: "设置" },
];

function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [guideOpen, setGuideOpen] = useState(false);
  const selectedKey =
    MENU_ITEMS.find((item) => item.key !== "/" && location.pathname.startsWith(item.key))?.key ??
    "/";

  useEffect(() => {
    if (consumeFirstVisitGuide()) setGuideOpen(true);
  }, []);

  /**
   * 在线体验模式：接收官网 iframe 发来的切页指令。
   *
   * 动态 import 是刻意的——静态引入会让 `src/demo/*` 进入主发行包的依赖图。
   * 演示构建里这一段会真正跑起来；普通构建里 `import.meta.env.VITE_DEMO_MODE`
   * 恒为 undefined，条件永假，打包器把整块摇掉。
   */
  useEffect(() => {
    if (import.meta.env.VITE_DEMO_MODE !== "1") return;
    let uninstall: (() => void) | undefined;
    void import("./demo/demoBridge").then(({ installDemoBridge }) => {
      uninstall = installDemoBridge(navigate);
    });
    return () => uninstall?.();
  }, [navigate]);

  const navigateFromGuide = (path: string) => {
    navigate(path);
  };

  return (
    <>
      {/* 批次完成全局通知：挂在布局层，投递/采集跑完时无论用户在哪个页面都能收到。 */}
      <TaskCompletionNotifier />
      <Layout className="app-shell">
        <Sider className="app-sider" theme="light" width={200} breakpoint="lg" collapsedWidth={64}>
          <div className="app-brand">
            <span className="app-brand-mark">
              {/* 用 import 拿到带 base 前缀的 URL，不要写死 "/resumeforge-icon.png"：
                  在线体验构建把产物部署在 GitHub Pages 的**子路径**（base: "./"）下，
                  写死的绝对路径会指到域名根目录、图标 404。import 由 Vite 按 base 重写。 */}
              <img className="app-brand-image" src={brandIcon} alt="" />
            </span>
            <span className="app-brand-copy">
              <span className="app-brand-name">{APP_NAME}</span>
              <span className="app-brand-caption">AI 简历工作台</span>
            </span>
          </div>
          <Menu
            className="app-nav-menu"
            theme="light"
            mode="inline"
            selectedKeys={[selectedKey]}
            items={MENU_ITEMS}
            onClick={({ key }) => navigate(key)}
          />
          <div className="app-sider-footer">
            <div className="app-sider-footer-row">
              <Tooltip title="使用指南" placement="right">
                <Button
                  className="app-guide-button"
                  type="text"
                  icon={<QuestionCircleOutlined />}
                  onClick={() => setGuideOpen(true)}
                  aria-label="使用指南"
                >
                  <span className="app-guide-label">使用指南</span>
                </Button>
              </Tooltip>
              {/* 开源仓库入口在页头右上角（见下面的 Header）。页脚这一行是
                  「使用指南 + 检查更新」：都是"偶尔想确认一下"的低频动作，凑在左下角。 */}
              <UpdateCheckButton />
            </div>
          </div>
        </Sider>
        <Layout className="app-main">
          <Header className="app-header">
            <Typography.Text strong className="app-header-title">
              AI 定制化简历生成平台
            </Typography.Text>
            <div className="app-header-actions">
              {/* 左侧是"我当前在哪个数据集、用的哪张照片"，右侧是全局动作（源码 / 退出）。
                  两者之间用一根细分隔线隔开，避免四个元素挤成一条。 */}
              <AppHeaderContext />
              {/* 有任务在跑时才出现：平时页头不该多一个空按钮。 */}
              <BackgroundTasksIndicator />
              <span className="app-header-divider" aria-hidden="true" />
              {/* GitHub 入口在页头右上角：与「退出」并排。
                  它是"关于本项目"这类低频、跨页面的入口，放右上角既符合习惯，
                  也不必让用户先找到侧栏底部。 */}
              {GITHUB_REPO && (
                <Tooltip title="在 GitHub 上查看源码 / 反馈问题">
                  <Button
                    className="app-repo-button"
                    type="text"
                    icon={<GithubOutlined />}
                    href={GITHUB_REPO}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`在 GitHub 上查看 ${APP_NAME} 源码`}
                  />
                </Tooltip>
              )}
              <ExitAppButton />
            </div>
          </Header>
          <Content className="app-content">
            <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
              <Outlet />
            </Suspense>
          </Content>
        </Layout>
      </Layout>
      {guideOpen && (
        <Suspense fallback={null}>
          <UserGuideModal open onClose={() => setGuideOpen(false)} onNavigate={navigateFromGuide} />
        </Suspense>
      )}
    </>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<MainLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/resumes" element={<ResumesPage />} />
        <Route path="/apply" element={<ApplyPage />} />
        <Route path="/tracker" element={<TrackerPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/favorites" element={<FavoritesPage />} />
        <Route path="/assistant" element={<AssistantPage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/skills" element={<SkillsPage />} />
        <Route path="/interview" element={<InterviewPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/claims" element={<ClaimsPage />} />
        <Route path="/trash" element={<TrashPage />} />
        <Route path="/claims/drill" element={<DrillPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
