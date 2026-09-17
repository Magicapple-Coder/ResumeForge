/**
 * 投递专用浏览器：启动 / 停止 / 状态检查。
 *
 * 这是本应用**唯一**会访问招聘网站的窗口，因此界面上必须把两件事说清楚：
 * 1. 它是**投递专用的独立窗口**（独立 user-data-dir），不是你日常那个浏览器；
 * 2. 首次使用要在弹出的窗口里**自己扫码登录一次**——应用不存密码、不读 Cookie，
 *    登录态由 Chromium 自己持久化。
 */
import {
  ChromeOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Alert, App, Button, Space, Tag, Tooltip, Typography } from "antd";
import { useState } from "react";
import { getBrowserStatus, openBrowserSite, startBrowser, stopBrowser } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import { BROWSER_STATE_META, type BrowserStatus } from "../../types";

export default function BrowserStatusBar() {
  const { message } = App.useApp();
  const { data, loading, error, reload, setData } = useApi<BrowserStatus>(getBrowserStatus, []);
  const [busy, setBusy] = useState(false);

  const handleStart = async () => {
    setBusy(true);
    try {
      const status = await startBrowser();
      setData(status);
      message.success("投递专用浏览器已启动，请在弹出的窗口里扫码登录一次");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "启动投递专用浏览器失败");
    } finally {
      setBusy(false);
    }
  };

  const handleOpenSite = async () => {
    setBusy(true);
    try {
      const status = await openBrowserSite();
      setData(status);
      message.success("已在该窗口里打开招聘网站，请在里面扫码登录");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "打开招聘网站失败");
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setBusy(true);
    try {
      await stopBrowser();
      message.success("已关闭投递专用浏览器");
      await reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "关闭投递专用浏览器失败");
    } finally {
      setBusy(false);
    }
  };

  const state = data?.state ?? "unknown";
  const meta = BROWSER_STATE_META[state];
  const running = state === "running";
  // 标签页被用户关掉或跳走时用它把招聘网站找回来，不必重启浏览器。
  const canOpenSite = running && Boolean(data?.entry_url);

  return (
    <div className="apply-browser-bar">
      <Space wrap align="center" size={12}>
        <Space size={8} align="center">
          <ChromeOutlined />
          <Typography.Text strong>投递专用浏览器</Typography.Text>
          <Tag color={meta.color}>{meta.label}</Tag>
          {loading && <Typography.Text type="secondary">读取中…</Typography.Text>}
          {data && !loading && (
            <Typography.Text type="secondary">调试端口 {data.port}</Typography.Text>
          )}
        </Space>
        <Space wrap>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={busy}
            disabled={running}
            onClick={() => void handleStart()}
          >
            启动浏览器
          </Button>
          <Tooltip
            title={
              canOpenSite
                ? "在这个窗口里重新打开招聘网站首页"
                : "浏览器启动后可用；用于标签页被关掉或跳走时找回登录页"
            }
          >
            <Button
              icon={<LinkOutlined />}
              loading={busy}
              disabled={!canOpenSite}
              onClick={() => void handleOpenSite()}
            >
              打开招聘网站
            </Button>
          </Tooltip>
          <Button
            icon={<StopOutlined />}
            loading={busy}
            disabled={!running && state !== "starting"}
            onClick={() => void handleStop()}
          >
            关闭浏览器
          </Button>
          <Tooltip title="重新检查当前状态">
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void reload()}
              aria-label="刷新浏览器状态"
            >
              刷新状态
            </Button>
          </Tooltip>
        </Space>
      </Space>

      <Typography.Paragraph type="secondary" className="apply-browser-hint">
        投递与采集都在这个<Typography.Text strong>独立窗口</Typography.Text>
        里进行（用的是专用数据目录，和你日常的浏览器互不影响）。点「启动浏览器」后，这个窗口会
        <Typography.Text strong>直接打开招聘网站首页</Typography.Text>
        ，请在那里扫码登录一次——登录由你自己完成，应用不保存密码、Cookie
        或验证码；登录态由浏览器自己保留，下次启动无需重复登录。若你把标签页关掉或跳到了别处，
        点「打开招聘网站」即可找回来，不用重启浏览器。
      </Typography.Paragraph>

      {data?.logged_in_hint && (
        <Alert type="info" showIcon message={data.logged_in_hint} style={{ marginTop: 8 }} />
      )}
      {data?.entry_url && (
        <Typography.Paragraph type="secondary" className="apply-browser-path">
          站点入口：{data.entry_url}
        </Typography.Paragraph>
      )}
      {data?.browser_path && (
        <Typography.Paragraph type="secondary" className="apply-browser-path">
          使用浏览器：
          {data.browser_name ? `${data.browser_name}（${data.browser_path}）` : data.browser_path}
        </Typography.Paragraph>
      )}
      {error && <Alert type="error" showIcon message={error} style={{ marginTop: 8 }} />}
    </div>
  );
}
