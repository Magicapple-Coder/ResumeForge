/**
 * 后台任务登记表：关掉等待窗口之后，任务仍然被追踪。
 *
 * 这一层是"完成提醒"能兑现的前提——它以前挂在生成弹窗里，弹窗一关轮询就停了。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ResumeGenerateTask } from "../types";
import {
  attachTaskUi,
  cancelBackgroundTask,
  getBackgroundTasks,
  resetBackgroundTasks,
  subscribeBackgroundTasks,
  watchResumeTask,
} from "./backgroundTasks";
import { registerNotifyHost } from "./taskNotify";

const apiMocks = vi.hoisted(() => ({
  getResumeGenerateTask: vi.fn(),
  cancelResumeGenerateTask: vi.fn(),
}));

vi.mock("../api/resumes", () => ({
  getResumeGenerateTask: apiMocks.getResumeGenerateTask,
  cancelResumeGenerateTask: apiMocks.cancelResumeGenerateTask,
}));

const notices: { title: string; modal?: boolean; kind?: string }[] = [];

function makeTask(overrides: Partial<ResumeGenerateTask> = {}): ResumeGenerateTask {
  return {
    id: 7,
    status: "running",
    resume_id: null,
    error: "",
    message: "正在写第 1 段",
    received_chars: 120,
    job_id: null,
    title: "",
    created_at: "2026-09-25T00:00:00",
    started_at: "2026-09-25T00:00:00",
    finished_at: null,
    ...overrides,
  };
}

/**
 * 推进若干轮轮询。
 *
 * 多推几轮而不是精确一轮：登记表在登记时会立刻拉一次，那一次是异步的，完成时机与
 * 定时器推进的先后没有保证（单独跑稳定，整个测试套件并行时会偶发差一拍）。
 */
async function runOneTick(rounds = 3): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await vi.advanceTimersByTimeAsync(1600);
  }
}

beforeEach(() => {
  resetBackgroundTasks();
  notices.length = 0;
  apiMocks.getResumeGenerateTask.mockReset();
  apiMocks.cancelResumeGenerateTask.mockReset();
  registerNotifyHost({
    notification: {
      success: (config) => notices.push({ title: String(config.message), modal: false }),
      warning: (config) =>
        notices.push({ title: String(config.message), modal: false, kind: "warning" }),
      error: (config) =>
        notices.push({ title: String(config.message), modal: false, kind: "error" }),
      info: (config) => notices.push({ title: String(config.message), modal: false }),
    },
    modal: {
      // AntD 的 modal 认 title / content（不是 message）——曾经就因为传了 message，
      // 弹窗标题与正文全空。假宿主按真实形状记录，测试才能钉住这一点。
      info: (config) => notices.push({ title: String(config.title), modal: true, kind: "modal" }),
    },
  });
  vi.useFakeTimers();
});

describe("后台任务登记表", () => {
  it("登记后能被订阅到，并带上进度", async () => {
    const seen: number[] = [];
    const unsubscribe = subscribeBackgroundTasks((tasks) => seen.push(tasks.length));

    watchResumeTask(makeTask(), "生成通用简历");
    expect(getBackgroundTasks()).toEqual([
      expect.objectContaining({ id: 7, label: "生成通用简历", message: "正在写第 1 段" }),
    ]);
    expect(seen.length).toBeGreaterThan(0);
    unsubscribe();
  });

  it("完成时用统一出口提醒并自动从列表消失", async () => {
    apiMocks.getResumeGenerateTask.mockResolvedValue(
      makeTask({ status: "completed", resume_id: 42 }),
    );
    watchResumeTask(makeTask(), "生成通用简历");

    await runOneTick();

    expect(notices.some((item) => item.title === "简历已生成")).toBe(true);
    expect(getBackgroundTasks()).toEqual([]);
  });

  it("用户已经离开（界面没在看）时用居中弹窗；还在看时只用卡片", async () => {
    apiMocks.getResumeGenerateTask.mockResolvedValue(
      makeTask({ status: "completed", resume_id: 1 }),
    );
    watchResumeTask(makeTask(), "生成通用简历");
    const detach = attachTaskUi(7);

    await runOneTick();
    expect(notices.find((item) => item.title === "简历已生成")?.modal).toBe(false);

    // 第二次：没人 attach
    resetBackgroundTasks();
    notices.length = 0;
    apiMocks.getResumeGenerateTask.mockResolvedValue(
      makeTask({ status: "completed", resume_id: 1 }),
    );
    watchResumeTask(makeTask({ id: 8 }), "生成通用简历");
    await runOneTick();
    expect(notices.find((item) => item.title === "简历已生成")?.modal).toBe(true);

    detach();
  });

  it("失败也提醒（失败比成功更需要知道）", async () => {
    apiMocks.getResumeGenerateTask.mockResolvedValue(
      makeTask({ status: "failed", error: "模型返回为空" }),
    );
    watchResumeTask(makeTask(), "生成通用简历");

    await runOneTick();

    expect(notices.some((item) => item.title === "简历生成失败")).toBe(true);
  });

  it("轮询失败不会假报完成（等下一轮自愈）", async () => {
    apiMocks.getResumeGenerateTask.mockRejectedValue(new Error("后端暂时不可用"));
    watchResumeTask(makeTask(), "生成通用简历");

    await runOneTick();

    expect(notices).toEqual([]);
    expect(getBackgroundTasks().length).toBe(1);
  });

  it("取消会把任务置为取消态并通知", async () => {
    apiMocks.cancelResumeGenerateTask.mockResolvedValue(makeTask({ status: "cancelled" }));
    watchResumeTask(makeTask(), "生成通用简历");

    await cancelBackgroundTask(7);

    expect(apiMocks.cancelResumeGenerateTask).toHaveBeenCalledWith(7);
    expect(notices.some((item) => item.title === "简历生成已取消")).toBe(true);
    expect(getBackgroundTasks()).toEqual([]);
  });
});
