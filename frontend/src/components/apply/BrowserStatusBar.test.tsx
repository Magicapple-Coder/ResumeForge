/**
 * 投递专用浏览器工具条的交互测试。
 *
 * 重点盯住"启动浏览器"这件事的可用性：只开一个空白窗口是没有意义的，
 * 用户需要的是那个能扫码登录的招聘网站页面，所以这里验证
 * 「打开招聘网站」按钮的可用性条件与点击行为。
 *
 * 另一组盯住"关闭浏览器"：后端重启后浏览器仍在跑、句柄却丢了，这种窗口**关不掉**。
 * 按钮必须置灰**并且把原因写在页面上**——禁用按钮不派发鼠标事件，挂在悬停提示里的
 * 解释等于没写。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BrowserStatus } from "../../types";
import BrowserStatusBar from "./BrowserStatusBar";

const apiMocks = vi.hoisted(() => ({
  getBrowserStatus: vi.fn(),
  startBrowser: vi.fn(),
  stopBrowser: vi.fn(),
  openBrowserSite: vi.fn(),
}));

vi.mock("../../api/apply", () => ({ ...apiMocks }));

const apiState = vi.hoisted(() => ({
  data: null as BrowserStatus | null,
  loading: false,
  error: null as string | null,
  reload: vi.fn(),
  setData: vi.fn(),
}));

vi.mock("../../hooks/useApi", () => ({
  useApi: () => apiState,
}));

const RUNNING_WITH_ENTRY: BrowserStatus = {
  state: "running",
  port: 9333,
  profile_dir: "C:/data/browser-profile",
  browser_path: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  browser_name: "Google Chrome",
  entry_url: "https://www.zhipin.com/",
  logged_in_hint: "首次使用请在弹出的浏览器窗口里扫码登录一次。",
  owned: true,
};

const STOPPED: BrowserStatus = {
  ...RUNNING_WITH_ENTRY,
  state: "stopped",
  browser_path: "",
  browser_name: "",
  owned: false,
};

/** 上一次运行留下的窗口：端口在答（照常能用），但本进程没有它的句柄，关不掉。 */
const RUNNING_FROM_A_PREVIOUS_RUN: BrowserStatus = {
  ...RUNNING_WITH_ENTRY,
  owned: false,
};

function renderBar() {
  return render(
    <AntdApp>
      <BrowserStatusBar />
    </AntdApp>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiState.data = null;
  apiState.loading = false;
  apiState.error = null;
});

// 项目未开启 vitest globals，自动清理不会生效，必须显式注册，
// 否则上一个用例渲染的组件会残留导致查询命中多个元素。
afterEach(cleanup);

describe("BrowserStatusBar", () => {
  it("浏览器未启动时禁用「打开招聘网站」，避免点了没反应", () => {
    apiState.data = STOPPED;
    renderBar();

    expect(screen.getByRole("button", { name: /打开招聘网站/ })).toBeDisabled();
  });

  it("浏览器运行中时「打开招聘网站」可用，点击会请求后端导航", async () => {
    apiState.data = RUNNING_WITH_ENTRY;
    apiMocks.openBrowserSite.mockResolvedValue(RUNNING_WITH_ENTRY);
    renderBar();

    const openButton = screen.getByRole("button", { name: /打开招聘网站/ });
    expect(openButton).toBeEnabled();

    fireEvent.click(openButton);

    await waitFor(() => expect(apiMocks.openBrowserSite).toHaveBeenCalledTimes(1));
  });

  it("站点没有配置入口地址时不提供这个按钮能力", () => {
    apiState.data = { ...RUNNING_WITH_ENTRY, entry_url: "" };
    renderBar();

    expect(screen.getByRole("button", { name: /打开招聘网站/ })).toBeDisabled();
  });

  it("展示站点入口地址，让用户知道这个窗口会去哪里", () => {
    apiState.data = RUNNING_WITH_ENTRY;
    renderBar();

    expect(screen.getByText(/站点入口/)).toHaveTextContent("https://www.zhipin.com/");
  });

  it("展示实际使用的浏览器名，而不只是一串路径", () => {
    apiState.data = RUNNING_WITH_ENTRY;
    renderBar();

    expect(screen.getByText(/使用浏览器/)).toHaveTextContent("Google Chrome");
  });

  it("本次运行启动的窗口可以关闭", () => {
    apiState.data = RUNNING_WITH_ENTRY;
    renderBar();

    expect(screen.getByRole("button", { name: /关闭浏览器/ })).toBeEnabled();
  });

  it("未启动时没有可关的窗口", () => {
    apiState.data = STOPPED;
    renderBar();

    expect(screen.getByRole("button", { name: /关闭浏览器/ })).toBeDisabled();
  });

  it("上一次运行留下的窗口照常可用，但关不掉——原因直接写在页面上", () => {
    // 后端重启会丢掉进程句柄，而应用只关自己拉起的窗口（绝不按 PID 去猜）。
    // 这种窗口照样能采集、能投递，所以状态仍是"运行中"，只有关闭能力被收回。
    apiState.data = RUNNING_FROM_A_PREVIOUS_RUN;
    renderBar();

    expect(screen.getByRole("button", { name: /关闭浏览器/ })).toBeDisabled();
    // 光置灰不够：用户会以为按钮坏了。原因必须可见，不能藏在悬停提示里
    // （禁用按钮不派发鼠标事件，Tooltip 根本弹不出来）。
    expect(screen.getByText(/上一次运行/)).toBeInTheDocument();
    expect(screen.getByText(/采集与投递不受影响/)).toBeInTheDocument();
  });

  it("浏览器是本次启动时不显示那段说明，避免噪音", () => {
    apiState.data = RUNNING_WITH_ENTRY;
    renderBar();

    expect(screen.queryByText(/关不掉它/)).not.toBeInTheDocument();
  });
});
