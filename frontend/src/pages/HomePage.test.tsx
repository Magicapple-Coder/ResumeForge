/** 首页：快捷入口、全局搜索（含"更多结果"分组跳转）、近期提醒卡片与启动弹窗。 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import HomePage from "./HomePage";

const apiMocks = vi.hoisted(() => ({ getStats: vi.fn(), searchAll: vi.fn() }));

vi.mock("../api/search", () => apiMocks);

const reminderApiMocks = vi.hoisted(() => ({ listUpcomingReminders: vi.fn() }));

vi.mock("../api/reminders", () => reminderApiMocks);

const settingsApiMocks = vi.hoisted(() => ({ getReminderPopupSetting: vi.fn() }));

vi.mock("../api/settings", () => settingsApiMocks);

const STATS = {
  job_count: 3,
  open_job_count: 2,
  resume_count: 1,
  week_resume_count: 0,
  latest_jobs: [],
  latest_resumes: [],
  favorite_job_count: 0,
  pending_claim_count: 0,
  pending_claims: [],
  stalled_application_count: 0,
  apply_queue_count: 0,
  latest_applications: [],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiMocks.getStats.mockReset().mockResolvedValue(STATS);
  apiMocks.searchAll.mockReset().mockResolvedValue({ jobs: [], resumes: [], more: [] });
  reminderApiMocks.listUpcomingReminders.mockReset().mockResolvedValue([]);
  settingsApiMocks.getReminderPopupSetting.mockReset().mockResolvedValue({ enabled: false });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("HomePage", () => {
  it("renders the updated quick entries", async () => {
    renderPage();

    expect(await screen.findByText("求职统计")).toBeInTheDocument();
    expect(screen.getByText("模拟面试·题库")).toBeInTheDocument();
    expect(screen.getByText("内推管理")).toBeInTheDocument();
    expect(screen.getByText("日历提醒")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: /求职统计/ })).toHaveAttribute("href", "/analytics");
    expect(screen.getByRole("link", { name: /模拟面试·题库/ })).toHaveAttribute("href", "/interview");
    expect(screen.getByRole("link", { name: /内推管理/ })).toHaveAttribute("href", "/apply");
    expect(screen.getByRole("link", { name: /日历提醒/ })).toHaveAttribute("href", "/tracker");
  });

  it("renders grouped more-results that navigate by hit path", async () => {
    apiMocks.searchAll.mockResolvedValue({
      jobs: [],
      resumes: [],
      more: [
        { type: "referral", id: 1, title: "后端内推", subtitle: "字节跳动", path: "/apply" },
        { type: "reminder", id: 2, title: "催HR回复", subtitle: "", path: "/tracker" },
      ],
    });

    renderPage();
    await screen.findByText("求职统计");

    fireEvent.change(screen.getByPlaceholderText(/搜索岗位/), { target: { value: "后端" } });
    fireEvent.click(screen.getByRole("button", { name: /搜\s*索/ }));

    expect(await screen.findByText("更多结果（2）")).toBeInTheDocument();
    expect(screen.getByText("内推（1）")).toBeInTheDocument();
    expect(screen.getByText("提醒（1）")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "后端内推" })).toHaveAttribute("href", "/apply");
    expect(screen.getByRole("link", { name: "催HR回复" })).toHaveAttribute("href", "/tracker");
  });

  it("does not render the more-results block when there are no hits", async () => {
    renderPage();
    await screen.findByText("求职统计");

    fireEvent.change(screen.getByPlaceholderText(/搜索岗位/), { target: { value: "无结果" } });
    fireEvent.click(screen.getByRole("button", { name: /搜\s*索/ }));

    expect(await screen.findByText("匹配的岗位（0）")).toBeInTheDocument();
    expect(screen.queryByText(/更多结果/)).toBeNull();
  });

  it("renders the upcoming reminders card with urgency colors and navigation", async () => {
    reminderApiMocks.listUpcomingReminders.mockResolvedValue([
      {
        id: 1,
        title: "参加某司二面",
        remind_at: "2026-09-21T10:00:00",
        kind: "interview",
        status: "pending",
        track_id: null,
        job_id: null,
        resume_id: null,
        note: "",
        created_at: "2026-09-19T08:00:00",
        updated_at: "2026-09-19T08:00:00",
        urgency: "soon",
        due_label: "明天",
      },
      {
        id: 2,
        title: "催 HR 回复",
        remind_at: "2026-09-18T10:00:00",
        kind: "hr_reply",
        status: "pending",
        track_id: null,
        job_id: null,
        resume_id: null,
        note: "",
        created_at: "2026-09-19T08:00:00",
        updated_at: "2026-09-19T08:00:00",
        urgency: "overdue",
        due_label: "已逾期 2 天",
      },
    ]);

    renderPage();

    expect(await screen.findByText("近期提醒")).toBeInTheDocument();
    expect(screen.getByText("参加某司二面")).toBeInTheDocument();
    expect(screen.getByText("催 HR 回复")).toBeInTheDocument();

    // 紧急度分色：soon=橙、overdue=红。
    expect(screen.getByText("明天").closest(".ant-tag")).toHaveClass("ant-tag-orange");
    expect(screen.getByText("已逾期 2 天").closest(".ant-tag")).toHaveClass("ant-tag-red");

    // 点击提醒标题跳到 /tracker。
    expect(screen.getByRole("link", { name: "参加某司二面" })).toHaveAttribute("href", "/tracker");
  });

  it("shows a startup popup only when enabled and reminders exist", async () => {
    settingsApiMocks.getReminderPopupSetting.mockResolvedValue({ enabled: true });
    reminderApiMocks.listUpcomingReminders.mockResolvedValue([
      {
        id: 1,
        title: "参加某司二面",
        remind_at: "2026-09-21T10:00:00",
        kind: "interview",
        status: "pending",
        track_id: null,
        job_id: null,
        resume_id: null,
        note: "",
        created_at: "2026-09-19T08:00:00",
        updated_at: "2026-09-19T08:00:00",
        urgency: "soon",
        due_label: "今天",
      },
    ]);

    renderPage();

    expect(await screen.findByText("参加某司二面")).toBeInTheDocument();
    // 弹窗出现：只有启动弹窗才有「知道了」按钮（卡片里没有）。
    expect(await screen.findByRole("button", { name: /知道了/ })).toBeInTheDocument();
  });
});
