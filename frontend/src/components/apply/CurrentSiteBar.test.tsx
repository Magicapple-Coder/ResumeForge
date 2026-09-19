/**
 * 当前招聘网站提示条（含站点健康度 degraded 标记）的交互测试。
 *
 * 重点盯住两件事：
 * - **只在 degraded 时**显示告警标记——健康站点不该被加装饰（否则用户会习惯性忽略它）；
 * - 原因文案**来自后端** `reasons`，前端不再自己写一套判据，也不该把它翻译/裁剪掉。
 *
 * aria-label 用后端原因文本，既让辅助技术可读，也给这里一个稳定的查询条件。
 */
import { App as AntdApp } from "antd";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SiteHealthList, SiteList } from "../../types";
import CurrentSiteBar from "./CurrentSiteBar";

const apiMocks = vi.hoisted(() => ({
  listSites: vi.fn(),
  getSiteHealth: vi.fn(),
}));

vi.mock("../../api/apply", () => ({ ...apiMocks }));

// 组件会调用两次 useApi（站点清单 + 站点健康度），按传入的 fetcher 身份分发到不同的状态，
// 否则两个数据源会共用同一份 mock 数据、互相污染。
const sitesState = vi.hoisted(() => ({
  data: null as SiteList | null,
  loading: false,
  error: "" as string,
  reload: vi.fn(),
  setData: vi.fn(),
}));
const healthState = vi.hoisted(() => ({
  data: null as SiteHealthList | null,
  loading: false,
  error: "" as string,
  reload: vi.fn(),
  setData: vi.fn(),
}));

vi.mock("../../hooks/useApi", () => ({
  useApi: (fetcher: unknown) => (fetcher === apiMocks.getSiteHealth ? healthState : sitesState),
}));

const SITE_LIST: SiteList = {
  current: "boss",
  sites: [
    {
      key: "boss",
      display_name: "BOSS直聘",
      host: "zhipin.com",
      entry_url: "https://www.zhipin.com/",
      supports_collect: true,
      supports_apply: true,
    },
  ],
};

const DEGRADED_REASON =
  "最近 5 次采集里有 3 次读不出岗位页面（页面结构变化 / 选择器失效），站点可能改版了——" +
  "先重试一次；如果一直这样，请到项目仓库反馈并附上「采集记录」里的这次批次。";

const HEALTH_OK: SiteHealthList = {
  sites: [
    {
      site_key: "boss",
      display_name: "BOSS直聘",
      status: "ok",
      reasons: [],
      sampled: 5,
      selector_failures: 0,
      detail_drift_runs: 0,
      recent: [],
    },
  ],
};

const HEALTH_DEGRADED: SiteHealthList = {
  sites: [
    {
      site_key: "boss",
      display_name: "BOSS直聘",
      status: "degraded",
      reasons: [DEGRADED_REASON],
      sampled: 5,
      selector_failures: 3,
      detail_drift_runs: 0,
      recent: [],
    },
  ],
};

function renderBar() {
  return render(
    <AntdApp>
      <CurrentSiteBar />
    </AntdApp>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  sitesState.data = SITE_LIST;
  healthState.data = HEALTH_OK;
});

// 项目未开启 vitest globals，自动清理不会生效，必须显式注册。
afterEach(cleanup);

describe("CurrentSiteBar 站点健康度", () => {
  it("健康站点不显示任何告警标记", () => {
    renderBar();

    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("degraded 时显示可读的告警标记", () => {
    healthState.data = HEALTH_DEGRADED;
    renderBar();

    expect(screen.getByRole("alert", { name: /站点健康度/ })).toBeInTheDocument();
    expect(screen.getByText("站点可能已改版")).toBeInTheDocument();
  });

  it("原因文案来自后端 reasons，前端不自行编造", () => {
    healthState.data = HEALTH_DEGRADED;
    renderBar();

    // 哨兵：这条原因只存在于 mock 的后端返回里；页面能显示它，说明文案确实来自后端。
    expect(screen.getByText(DEGRADED_REASON)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveAccessibleName(
      expect.stringContaining(DEGRADED_REASON),
    );
  });

  it("站点清单缺失时不渲染（不挡其它功能）", () => {
    sitesState.data = null;
    renderBar();

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/当前招聘网站/)).toBeNull();
  });

  it("健康站点不新增任何告警节点或装饰（与改动前一致）", () => {
    const { container } = renderBar();

    // 改动前这里只有基础提示条。健康站点不该因为新功能多出空节点 / 分隔符 / 装饰——
    // 一旦多出来，用户会习惯性忽略这块区域，真出问题时也就看不见了。
    expect(container.querySelector(".apply-site-bar-health")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/当前招聘网站/)).toBeInTheDocument();
    expect(screen.getByText("BOSS直聘")).toBeInTheDocument();
    expect(screen.getByText(/目前仅支持这一个招聘网站/)).toBeInTheDocument();
  });

  it("只认后端的 status：reasons 非空但 status 是 ok 时不告警", () => {
    // 判据的权威只在后端一处。前端不得因为 reasons 有内容就自己判一次——两处判据迟早漂移。
    healthState.data = {
      sites: [{ ...HEALTH_OK.sites[0], status: "ok", reasons: ["不该被展示的原因"] }],
    };
    renderBar();

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("不该被展示的原因")).toBeNull();
  });
});
