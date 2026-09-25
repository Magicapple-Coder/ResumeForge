/**
 * 官网采集页的浏览器状态条。
 *
 * 它守的是"渲染升级对只采官网的用户可见"：那个浏览器的启动入口原先只在投递台，而投递台的写
 * 适配器目前只有 BOSS 直聘——不用 BOSS 的用户没有任何理由去那一页点它，于是这条路径对
 * 他们等同于不存在。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BrowserStatus } from "../../types";
import OfficialBrowserBar from "./OfficialBrowserBar";

const apiMocks = vi.hoisted(() => ({
  getBrowserStatus: vi.fn(),
  startBrowser: vi.fn(),
  refreshBrowser: vi.fn(),
  restartBrowser: vi.fn(),
}));

vi.mock("../../api/apply", () => apiMocks);

function makeStatus(overrides: Partial<BrowserStatus> = {}): BrowserStatus {
  return {
    state: "stopped",
    port: 9222,
    profile_dir: "C:/runtime/browser",
    browser_path: "C:/Chrome/chrome.exe",
    browser_name: "Google Chrome",
    entry_url: "https://www.zhipin.com/",
    logged_in_hint: "",
    ...overrides,
  } as BrowserStatus;
}

function renderBar() {
  return render(
    <AntdApp>
      <OfficialBrowserBar />
    </AntdApp>,
  );
}

beforeEach(() => {
  for (const mock of Object.values(apiMocks)) mock.mockReset();
  apiMocks.getBrowserStatus.mockResolvedValue(makeStatus());
});

afterEach(cleanup);

describe("OfficialBrowserBar", () => {
  it("offers to start the browser when it is not running", async () => {
    renderBar();

    expect(await screen.findByText("未启动")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /启动浏览器/ })).toBeInTheDocument();
  });

  it("says why the browser matters for collection", async () => {
    renderBar();
    await screen.findByText("未启动");

    // 用户得知道"为什么要在这一页启动一个浏览器"，否则这条状态栏只是噪音。
    expect(screen.getByText(/只有开着它才读得到/)).toBeInTheDocument();
    // 启动后是个空白窗口，这一点要说清楚，免得用户以为浏览器没开成功。
    expect(screen.getByText(/启动后是一个空白窗口/)).toBeInTheDocument();
    expect(screen.getByText(/这次采集不需要登录/)).toBeInTheDocument();
  });

  it("starts the browser without opening any site page", async () => {
    apiMocks.startBrowser.mockResolvedValue(makeStatus({ state: "running" }));
    renderBar();

    fireEvent.click(await screen.findByRole("button", { name: /启动浏览器/ }));

    // **必须是 false**：这里是借浏览器当渲染引擎，不是要访问某个招聘网站。
    // 传 true（投递台那套默认）会让只想采某公司官网的用户，一点按钮就跳出一个招聘网站——
    // 而访问那个站点根本不是他这次的要求。
    await waitFor(() => expect(apiMocks.startBrowser).toHaveBeenCalledWith(false));
    expect(await screen.findByText("运行中")).toBeInTheDocument();
    // 采集期间关掉它会让后面的页面读不出来，所以要说（提示条里那句是常驻的）。
    expect(screen.getByText(/请保持开着/)).toBeInTheDocument();
  });

  it("hides the start button once it is running", async () => {
    apiMocks.getBrowserStatus.mockResolvedValue(makeStatus({ state: "running" }));
    renderBar();

    expect(await screen.findByText("运行中")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /启动浏览器/ })).not.toBeInTheDocument();
    // **不提供「关闭」**：在这里关掉会打断投递台正在跑的批次，那个动作的责任不在这一页。
    expect(screen.queryByRole("button", { name: /关闭|停止/ })).not.toBeInTheDocument();
  });

  it("can refresh or restart the running browser from the official collection page", async () => {
    apiMocks.getBrowserStatus.mockResolvedValue(makeStatus({ state: "running" }));
    apiMocks.refreshBrowser.mockResolvedValue(makeStatus({ state: "running" }));
    apiMocks.restartBrowser.mockResolvedValue(makeStatus({ state: "running" }));
    renderBar();

    fireEvent.click(await screen.findByRole("button", { name: /刷新浏览器/ }));
    await waitFor(() => expect(apiMocks.refreshBrowser).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /重启浏览器/ }));
    await waitFor(() => expect(apiMocks.restartBrowser).toHaveBeenCalledTimes(1));
  });

  it("surfaces a failed start instead of silently doing nothing", async () => {
    apiMocks.startBrowser.mockRejectedValue(new Error("找不到 Chrome"));
    renderBar();

    fireEvent.click(await screen.findByRole("button", { name: /启动浏览器/ }));

    expect(await screen.findByText(/找不到 Chrome/)).toBeInTheDocument();
  });
});
