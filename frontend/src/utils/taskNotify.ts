/**
 * 「生成 / 批次完成」的统一通知出口：一处负责"弹窗 + 提示声"。
 *
 * 为什么要统一：这类提醒散在各模块里会出现两种不一致——有的响、有的不响；有的在任何页面
 * 都能看到、有的只在当前页弹。用户的要求很直接："每个 AI 生成模块完成后都要弹窗提醒并发出
 * 提醒声"。所以把呈现方式与声音绑在一起，调用方只说"什么完成了、要不要打断我"。
 *
 * 两种呈现，按"值不值得打断"分：
 * - `notification`（右上角卡片）：默认。批次跑完、一次性解读完成——不必立刻停下手上的事。
 * - `modal`（居中弹窗）：用户**明确等了很久**的那件事（例如整份简历生成），或结果需要他
 *   立刻做选择（"去看简历 / 稍后"）。它会打断操作，所以不滥用。
 */
import { createElement } from "react";
import type { ReactNode } from "react";
import { playDoneSound } from "./notifySound";

export interface TaskDoneNotice {
  title: string;
  description?: ReactNode;
  kind?: "success" | "warning" | "error";
  /** 右上角卡片里的动作按钮（调用方用 JSX 构造）。 */
  actions?: ReactNode;
  /** 改成居中弹窗；`confirmLabel` 给出确认按钮文案。 */
  modal?: boolean;
  confirmLabel?: string;
  onConfirm?: () => void;
}

/** 右上角卡片（AntD `notification`）的字段名。 */
interface NotificationPayload {
  message: ReactNode;
  description?: ReactNode;
  duration?: number;
  actions?: ReactNode;
}

/**
 * 居中弹窗（AntD `modal`）的字段名。
 *
 * **必须与上面的卡片分开**：AntD 的 `modal.info` 认的是 `title` / `content`，而
 * `notification` 认的是 `message` / `description`。曾经两者共用一个 `message` 形状，
 * 结果弹窗**标题与正文都是空的**（AntD 收不到它认识的键，不报错，只是什么都不显示）。
 */
interface ModalPayload {
  title: ReactNode;
  content?: ReactNode;
  okText?: string;
  onOk?: () => void;
}

export interface NotifyHost {
  notification: {
    success: (config: NotificationPayload) => void;
    warning: (config: NotificationPayload) => void;
    error: (config: NotificationPayload) => void;
    info: (config: NotificationPayload) => void;
  };
  modal: { info: (config: ModalPayload) => void };
}

let host: NotifyHost | null = null;

/** App 挂载时注册一次（AntD 的 App 实例只能在 hooks 里拿，这里只存引用）。 */
export function registerNotifyHost(next: NotifyHost | null): void {
  host = next;
}

/**
 * 报告一件"完成了"的事：**一定**发声（除非用户关掉了），再按 `modal` 决定是否打断。
 *
 * 没有宿主时（单测、或 App 还没挂上）只发声不弹——静默跳过比抛异常好。
 */
export function notifyTaskDone(notice: TaskDoneNotice): void {
  playDoneSound();
  if (!host) return;
  if (notice.modal) {
    host.modal.info({
      title: notice.title,
      // 弹窗没有独立的"动作区"，把卡片用的动作按钮并进正文，别让它悄悄丢掉。
      // 用 createElement 而不是 JSX：本文件是 .ts（工具模块），不参与 JSX 编译。
      content:
        notice.description || notice.actions
          ? createElement(
              "div",
              null,
              notice.description,
              notice.actions
                ? createElement("div", { className: "task-notice-actions" }, notice.actions)
                : null,
            )
          : undefined,
      okText: notice.confirmLabel ?? "知道了",
      onOk: notice.onConfirm,
    });
    return;
  }
  const kind = notice.kind ?? "success";
  host.notification[kind]({
    message: notice.title,
    description: notice.description,
    actions: notice.actions,
    duration: 6,
  });
}
