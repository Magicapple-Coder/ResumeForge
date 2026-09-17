import {
  AuditOutlined,
  FileTextOutlined,
  FunnelPlotOutlined,
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
import ExitAppButton from "./components/common/ExitAppButton";
import { APP_NAME, APP_NAME_EN, GITHUB_REPO } from "./config";
import { consumeFirstVisitGuide } from "./utils/userGuide";

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
const SkillsPage = lazy(() => import("./pages/SkillsPage"));
const InterviewPage = lazy(() => import("./pages/InterviewPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const UserGuideModal = lazy(() => import("./components/UserGuideModal"));

const { Sider, Header, Content } = Layout;

const MENU_ITEMS = [
  { key: "/", icon: <HomeOutlined />, label: "首页" },
  { key: "/jobs", icon: <SearchOutlined />, label: "岗位广场" },
  { key: "/resumes", icon: <FileTextOutlined />, label: "简历中心" },
  { key: "/apply", icon: <SendOutlined />, label: "投递台" },
  { key: "/tracker", icon: <FunnelPlotOutlined />, label: "求职进度" },
  { key: "/favorites", icon: <StarOutlined />, label: "收藏夹" },
  { key: "/assistant", icon: <MessageOutlined />, label: "求职助手" },
  { key: "/interview", icon: <SolutionOutlined />, label: "模拟面试" },
  { key: "/materials", icon: <InboxOutlined />, label: "资料箱" },
  { key: "/skills", icon: <ToolOutlined />, label: "工作台" },
  { key: "/profile", icon: <ProfileOutlined />, label: "我的资料" },
  { key: "/claims", icon: <AuditOutlined />, label: "事实台账" },
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

  const navigateFromGuide = (path: string) => {
    navigate(path);
  };

  return (
    <>
      <Layout className="app-shell">
        <Sider className="app-sider" theme="light" width={200} breakpoint="lg" collapsedWidth={64}>
          <div className="app-brand">
            <span className="app-brand-mark">
              <img className="app-brand-image" src="/resumeforge-icon.png" alt="" />
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
            <div className="app-sider-footer-actions">
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
              <ExitAppButton />
            </div>
          </div>
        </Sider>
        <Layout className="app-main">
          <Header className="app-header">
            <Typography.Text strong className="app-header-title">
              AI 定制化简历生成平台
            </Typography.Text>
            {GITHUB_REPO && (
              <Typography.Link
                className="app-header-repo"
                href={GITHUB_REPO}
                target="_blank"
                rel="noopener noreferrer"
              >
                {APP_NAME_EN} · 开源项目
              </Typography.Link>
            )}
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
        <Route path="/favorites" element={<FavoritesPage />} />
        <Route path="/assistant" element={<AssistantPage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/skills" element={<SkillsPage />} />
        <Route path="/interview" element={<InterviewPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/claims" element={<ClaimsPage />} />
        <Route path="/claims/drill" element={<DrillPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
