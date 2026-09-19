/** 求职数据看板：指标卡 + 漏斗 + 趋势渲染。 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AnalyticsPage from "./AnalyticsPage";

const apiMocks = vi.hoisted(() => ({ getAnalyticsDashboard: vi.fn() }));

vi.mock("../api/analytics", () => apiMocks);

const DASHBOARD = {
  total_applications: 7,
  valid_applications: 6,
  interview_count: 2,
  interview_rate: 0.3333,
  assessment_count: 3,
  assessment_to_interview_count: 2,
  assessment_pass_rate: 0.6667,
  offer_count: 1,
  funnel: [
    { status: "applied", label: "已投递", count: 1 },
    { status: "screening", label: "筛选中", count: 1 },
    { status: "assessment", label: "测评/笔试", count: 1 },
    { status: "interview", label: "面试", count: 1 },
    { status: "offer", label: "Offer", count: 1 },
    { status: "rejected", label: "已结束", count: 1 },
    { status: "unknown", label: "待确认", count: 1 },
  ],
  trend: [
    { month: "2026-04", label: "4月", count: 0 },
    { month: "2026-05", label: "5月", count: 1 },
    { month: "2026-06", label: "6月", count: 2 },
    { month: "2026-07", label: "7月", count: 1 },
    { month: "2026-08", label: "8月", count: 3 },
    { month: "2026-09", label: "9月", count: 0 },
  ],
};

beforeEach(() => {
  apiMocks.getAnalyticsDashboard.mockReset().mockResolvedValue(DASHBOARD);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("AnalyticsPage", () => {
  it("渲染四个指标卡", async () => {
    render(<AnalyticsPage />);

    expect(await screen.findByText("投递总量")).toBeInTheDocument();
    expect(screen.getByText("面试率")).toBeInTheDocument();
    expect(screen.getByText("笔试通过率")).toBeInTheDocument();
    expect(screen.getByText("Offer 数")).toBeInTheDocument();
  });

  it("渲染漏斗主线与趋势柱状图（自绘 SVG）", async () => {
    render(<AnalyticsPage />);

    expect(await screen.findByText("已投递")).toBeInTheDocument();
    // 主线漏斗的标签。
    expect(screen.getByText("筛选中")).toBeInTheDocument();
    expect(screen.getByText("测评/笔试")).toBeInTheDocument();
    expect(screen.getByText("面试")).toBeInTheDocument();
    expect(screen.getByText("Offer")).toBeInTheDocument();
    // 分支（已结束/待确认）不进主线漏斗。
    expect(screen.queryByText("待确认")).toBeNull();
    // 趋势图柱子的月份标签。
    expect(screen.getByText("9月")).toBeInTheDocument();
    // 两张图都是 SVG。
    expect(screen.getByRole("img", { name: "求职漏斗" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "投递趋势" })).toBeInTheDocument();
  });

  it("默认拉 6 个月趋势，切换时间范围后按新窗口重新拉取", async () => {
    render(<AnalyticsPage />);

    await screen.findByText("投递总量");
    await waitFor(() => expect(apiMocks.getAnalyticsDashboard).toHaveBeenCalledWith(6));

    fireEvent.click(screen.getByText("近1年"));

    await waitFor(() => expect(apiMocks.getAnalyticsDashboard).toHaveBeenCalledWith(12));
  });
});
