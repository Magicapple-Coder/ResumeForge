/** 真实月历（E11）：按 remind_at 归集、周一起始的表头、月切换与紧凑色点。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import dayjs from "dayjs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Reminder } from "../../types";
import CalendarView from "./CalendarView";

const apiMocks = vi.hoisted(() => ({
  listReminders: vi.fn(),
}));

vi.mock("../../api/reminders", () => apiMocks);

/** 一条落在「当月第 3 天」的提醒：无论测试在几月跑，都保证在月格里可见。 */
function reminderInCurrentMonth(title: string): Reminder {
  return {
    id: 1,
    title,
    remind_at: dayjs().startOf("month").add(2, "day").hour(10).format("YYYY-MM-DDTHH:mm:ss"),
    kind: "interview",
    status: "pending",
    track_id: null,
    job_id: null,
    resume_id: null,
    note: "",
    created_at: "2026-09-01T08:00:00",
    updated_at: "2026-09-01T08:00:00",
  };
}

function renderView(reminders: Reminder[] = [], compact = false) {
  return render(
    <AntdApp>
      <CalendarView reminders={reminders} compact={compact} />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.listReminders.mockReset().mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("CalendarView", () => {
  it("渲染周一起始的表头与当月标题", async () => {
    renderView();

    // 组件先自拉 listReminders，加载完才画网格——先等列头出现。
    const headers = await screen.findAllByRole("columnheader");
    expect(headers.map((node) => node.textContent)).toEqual([
      "一",
      "二",
      "三",
      "四",
      "五",
      "六",
      "日",
    ]);

    // 标题是「YYYY 年 M 月」，跟随真实时钟，不在测试里写死。
    expect(screen.getByText(dayjs().format("YYYY 年 M 月"))).toBeInTheDocument();
  });

  it("把提醒按 remind_at 归集到月格并显示标题", async () => {
    renderView([reminderInCurrentMonth("参加某司二面")]);

    expect(await screen.findByText("参加某司二面")).toBeInTheDocument();
  });

  it("点「下个月」切换到下个月的标题", async () => {
    renderView();
    await screen.findAllByRole("columnheader");

    fireEvent.click(screen.getByRole("button", { name: "下个月" }));

    expect(screen.getByText(dayjs().add(1, "month").format("YYYY 年 M 月"))).toBeInTheDocument();
  });

  it("紧凑模式只画色点、不铺提醒标题", async () => {
    renderView([reminderInCurrentMonth("参加某司二面")], true);

    // 紧凑模式用于首页「近期提醒」卡：只给「这天有提醒」的信号，标题不进网格。
    await screen.findAllByRole("columnheader");
    expect(screen.queryByText("参加某司二面")).not.toBeInTheDocument();
  });
});
