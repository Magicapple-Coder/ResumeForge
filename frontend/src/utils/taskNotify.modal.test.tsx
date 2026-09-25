/**
 * 完成弹窗必须**真的有内容**。
 *
 * 这一条必须用**真实 AntD**（而不是假宿主）来钉：假宿主如果照着我们的字段名记录，无论传
 * 什么都能"通过"；而这次的事故恰恰是字段名对不上 AntD——`modal.info` 认 `title`/`content`，
 * 我们传了 `message`/`description`，AntD 不报错，只是**弹出一个空白窗**。只有让真 AntD 把
 * 它渲染出来，才能保证以后不会又悄悄变空。
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { App as AntdApp } from "antd";
import { useEffect } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { notifyTaskDone, registerNotifyHost, type NotifyHost } from "./taskNotify";

function NotifyHostBridge() {
  const { notification, modal } = AntdApp.useApp();
  useEffect(() => {
    registerNotifyHost({ notification, modal } as unknown as NotifyHost);
    return () => registerNotifyHost(null);
  }, [modal, notification]);
  return null;
}

function renderHost() {
  render(
    <AntdApp>
      <NotifyHostBridge />
    </AntdApp>,
  );
}

afterEach(() => {
  cleanup();
  registerNotifyHost(null);
});

describe("完成提醒的真实呈现", () => {
  it("居中弹窗带标题与说明（不是空白窗）", async () => {
    renderHost();

    notifyTaskDone({
      modal: true,
      title: "简历已生成",
      description: "已自动保存到简历中心，可以继续微调或导出。",
      confirmLabel: "知道了",
    });

    // 直接查 AntD 的弹窗结构：标题与正文分别是 .ant-modal-title / .ant-modal-confirm-content。
    // （不用 findByText 是因为弹窗有入场动画，文本节点出现时机不稳定。）
    await waitFor(() => {
      expect(document.querySelector(".ant-modal-title")?.textContent).toBe("简历已生成");
    });
    expect(document.querySelector(".ant-modal-confirm-content")?.textContent).toContain(
      "已自动保存到简历中心",
    );
    expect(screen.getByRole("button", { name: /知\s*道\s*了/ })).toBeInTheDocument();
  });

  it("右上角卡片同样带上标题与说明", async () => {
    renderHost();

    notifyTaskDone({ title: "岗位解读完成", description: "结果已经可以查看了。" });

    await waitFor(() => {
      expect(document.querySelector(".ant-notification-notice-message")?.textContent).toBe(
        "岗位解读完成",
      );
    });
    expect(document.querySelector(".ant-notification-notice-description")?.textContent).toContain(
      "结果已经可以查看了",
    );
  });

  it("弹窗里也会保留调用方给的动作按钮", async () => {
    renderHost();

    notifyTaskDone({
      modal: true,
      title: "官网采集完成",
      description: "共抓取 12 条岗位。",
      actions: <button type="button">去看岗位</button>,
    });

    await waitFor(() => {
      expect(document.querySelector(".ant-modal-title")?.textContent).toBe("官网采集完成");
    });
    expect(screen.getByRole("button", { name: "去看岗位" })).toBeInTheDocument();
  });
});
