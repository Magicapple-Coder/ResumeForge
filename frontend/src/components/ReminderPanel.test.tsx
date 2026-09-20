/** 日历提醒面板：列表渲染、标记完成、删除（软删）。 */
import { App as AntApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReminderPanel from "./ReminderPanel";

const apiMocks = vi.hoisted(() => ({
  listReminders: vi.fn(),
  createReminder: vi.fn(),
  updateReminder: vi.fn(),
  deleteReminder: vi.fn(),
}));

vi.mock("../api/reminders", () => apiMocks);

const ITEMS = [
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
  },
];

function renderPanel() {
  return render(
    <AntApp>
      <ReminderPanel trackOptions={[]} jobOptions={[]} resumeOptions={[]} />
    </AntApp>,
  );
}

beforeEach(() => {
  apiMocks.listReminders.mockReset().mockResolvedValue(ITEMS);
  apiMocks.updateReminder.mockReset().mockResolvedValue(undefined);
  apiMocks.deleteReminder.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ReminderPanel", () => {
  it("渲染提醒列表，带类型与状态标签", async () => {
    renderPanel();

    expect(await screen.findByText("参加某司二面")).toBeInTheDocument();
    expect(screen.getByText("面试")).toBeInTheDocument();
    expect(screen.getByText("待办")).toBeInTheDocument();
    expect(apiMocks.listReminders).toHaveBeenCalled();
  });

  it("待办提醒可一键标记完成（PATCH status=done）", async () => {
    renderPanel();
    await screen.findByText("参加某司二面");

    fireEvent.click(screen.getByRole("button", { name: /完成提醒 参加某司二面/ }));

    await waitFor(() =>
      expect(apiMocks.updateReminder).toHaveBeenCalledWith(1, { status: "done" }),
    );
  });

  it("删除先确认，确认后走软删除", async () => {
    renderPanel();
    await screen.findByText("参加某司二面");

    fireEvent.click(screen.getByRole("button", { name: /删除提醒 参加某司二面/ }));

    expect(apiMocks.deleteReminder).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "确认删除提醒 参加某司二面" }));

    await waitFor(() => expect(apiMocks.deleteReminder).toHaveBeenCalledWith(1));
  });

  it("读取失败时透出中文错误", async () => {
    apiMocks.listReminders.mockRejectedValue(new Error("读取提醒失败"));
    renderPanel();

    expect(await screen.findByText("读取提醒失败")).toBeInTheDocument();
  });
});
