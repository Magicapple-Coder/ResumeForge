/**
 * 批次完成全局通知：投递/采集批次结束后弹通知 + 系统级桌面通知。
 *
 * 放在全局布局（MainLayout）而非投递台页面：用户跳到任何页面（首页、简历中心……）
 * 都能收到"批次跑完了"的通知，点击即可跳回投递台。窗口在后台时，Web Notification
 * 让操作系统层面也能提示（能拿到权限就发，拿不到就只用应用内通知，绝不主动弹权限框）。
 */
import { BellOutlined } from "@ant-design/icons";
import { App } from "antd";
import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTaskCompletionWatcher } from "../hooks/useTaskCompletionWatcher";

const KIND_LABEL: Record<string, string> = {
  apply: "投递",
  collect: "采集",
};

/** 把批次终态转成一条用户可读的通知；返回 null 表示这种终态不值得打扰。 */
export function buildTaskNotification(detail: {
  id: number;
  kind: string;
  status: string;
  succeeded: number;
  failed: number;
  skipped: number;
  message: string;
}): {
  type: "success" | "info" | "warning" | "error";
  message: string;
  description: string;
} | null {
  const kindLabel = KIND_LABEL[detail.kind] ?? "任务";
  const stats =
    detail.kind === "apply"
      ? `成功 ${detail.succeeded} · 失败 ${detail.failed} · 跳过 ${detail.skipped}`
      : `已暂存 ${detail.succeeded} 个岗位 · 跳过 ${detail.skipped} 个`;
  switch (detail.status) {
    case "completed":
      return {
        type: "success",
        message: `${kindLabel}批次 #${detail.id} 已完成`,
        description: stats,
      };
    case "failed":
      return {
        type: "error",
        message: `${kindLabel}批次 #${detail.id} 失败`,
        description: detail.message || "请到投递台查看失败原因",
      };
    case "stopped":
      return {
        type: "warning",
        message: `${kindLabel}批次 #${detail.id} 已停止`,
        description: stats,
      };
    default:
      // 其余终态（理论上有 pause 类，但那些仍在"进行中"不会走到这）不通知。
      return null;
  }
}

/** 尽力发一条系统桌面通知；权限未授予时静默跳过，绝不主动弹权限申请。 */
export function fireWebNotification(title: string, body: string): void {
  try {
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    new Notification(title, { body });
  } catch {
    /* 通知失败不影响应用内通知。 */
  }
}

export default function TaskCompletionNotifier() {
  const { notification } = App.useApp();
  const navigate = useNavigate();

  const handleFinished = useCallback(
    ({
      detail,
    }: {
      detail: Parameters<typeof buildTaskNotification>[0] & { items?: unknown[] };
    }) => {
      const payload = buildTaskNotification(detail);
      if (!payload) return;
      fireWebNotification(payload.message, payload.description);
      notification[payload.type]({
        key: `task-finished-${detail.id}`,
        icon: <BellOutlined />,
        message: payload.message,
        description: (
          <span
            role="button"
            tabIndex={0}
            style={{ cursor: "pointer" }}
            onClick={() => navigate("/apply")}
            onKeyDown={(event) => {
              if (event.key === "Enter") navigate("/apply");
            }}
          >
            {payload.description}（点击查看投递台）
          </span>
        ),
        duration: 8,
        placement: "bottomRight",
      });
    },
    [notification, navigate],
  );

  useTaskCompletionWatcher(handleFinished);
  return null;
}
