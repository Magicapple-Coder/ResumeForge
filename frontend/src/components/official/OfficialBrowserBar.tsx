/**
 * 官网采集页的浏览器状态条。
 *
 * **它为什么必须在这里**：有些招聘页的内容要真实浏览器打开才读得到（前端框架渲染的列表），
 * 而采集的「渲染升级」用的正是应用那个浏览器实例（与投递台共用同一个，不另起第二个——用户
 * 可能已经在那里面登录过站点，多开一个既费内存又要再登一次）。
 *
 * 问题在于那个浏览器的**启动入口原先只在投递台**，而投递台的写适配器目前只覆盖一个招聘网站：
 * 只用官网采集、不走投递的用户没有任何理由去那一页点它，于是渲染升级对他们等同于不存在，
 * 而它恰好是这类站点唯一读得出来的路径。这一条状态栏就是把那个入口搬到用得着的地方。
 *
 * （文案里不写任何招聘网站的名字：前端生产代码不许硬编码站点信息，有守卫测试盯着。）
 *
 * 三条刻意的取舍：
 *
 * - **不提供「关闭」**。这里关掉会打断投递台正在跑的批次，而那个动作的责任不在这一页。
 * - **措辞中性**，不复用投递台那句"扫码登录"：采集**不需要**登录，它只需要浏览器开着。
 * - **启动时不打开任何站点页面**（`startBrowser(false)`）：这里借浏览器是当渲染引擎，
 *   采集哪一页由采集自己导航。投递台那套默认会打开站点入口页，用在这里就成了
 *   "我只想采某个公司的官网，一点按钮却跳出一个招聘网站"——访问那个站点根本不是这次的要求。
 */
import { ChromeOutlined } from "@ant-design/icons";
import { App, Button, Space, Tag, Tooltip, Typography } from "antd";
import { useState } from "react";
import { getBrowserStatus, refreshBrowser, restartBrowser, startBrowser } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import { BROWSER_STATE_META, type BrowserStatus } from "../../types";

export default function OfficialBrowserBar() {
  const { message } = App.useApp();
  const { data, loading, error, setData } = useApi<BrowserStatus>(getBrowserStatus, []);
  const [busy, setBusy] = useState(false);

  const state = data?.state ?? (error ? "unknown" : "stopped");
  const meta = BROWSER_STATE_META[state];
  const running = state === "running";

  const handleStart = async () => {
    setBusy(true);
    try {
      // 不打开站点入口页：这里要的是渲染引擎，不是那个招聘网站的登录页。
      setData(await startBrowser(false));
      message.success("浏览器已启动，采集期间请不要关掉它");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "启动浏览器失败");
    } finally {
      setBusy(false);
    }
  };

  const handleRefresh = async () => {
    setBusy(true);
    try {
      setData(await refreshBrowser());
      message.success("浏览器当前页面已刷新");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "刷新浏览器失败");
    } finally {
      setBusy(false);
    }
  };

  const handleRestart = async () => {
    setBusy(true);
    try {
      setData(await restartBrowser());
      message.success("浏览器已重启");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重启浏览器失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Space size={6} wrap>
      <Tooltip title="有些招聘页的内容要浏览器打开才有。这里用的是应用那个浏览器，与投递台共用同一个">
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          <ChromeOutlined /> 浏览器渲染
        </Typography.Text>
      </Tooltip>
      <Tag color={meta.color}>{meta.label}</Tag>
      {running ? (
        <>
          <Button size="small" loading={busy} onClick={() => void handleRefresh()}>
            刷新浏览器
          </Button>
          <Button size="small" loading={busy} onClick={() => void handleRestart()}>
            重启浏览器
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            需要渲染的页面会用它打开；采集期间请保持开着
          </Typography.Text>
        </>
      ) : (
        <>
          <Button size="small" loading={busy || loading} onClick={() => void handleStart()}>
            启动浏览器
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            前端渲染的招聘页（列表要等 JS 才出内容）只有开着它才读得到；
            启动后是一个空白窗口，采集需要渲染时会自己打开对应的页面，这次采集不需要登录
          </Typography.Text>
        </>
      )}
    </Space>
  );
}
