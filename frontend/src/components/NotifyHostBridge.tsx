/**
 * 把 AntD 的通知 / 弹窗实例注册到统一通知出口（`utils/taskNotify`）。
 *
 * 为什么需要这一层：`App.useApp()` 只能在组件里调用，而"生成完成后弹窗 + 发声"要在各种
 * 非组件上下文（异步回调、全局 watcher）里触发。这里在应用启动时把实例存进模块级单例，
 * 之后任何地方都能调 `notifyTaskDone`。
 */
import { App } from "antd";
import { useEffect } from "react";
import { registerNotifyHost, type NotifyHost } from "../utils/taskNotify";

export default function NotifyHostBridge() {
  const { notification, modal } = App.useApp();

  useEffect(() => {
    registerNotifyHost({ notification, modal } as unknown as NotifyHost);
    return () => registerNotifyHost(null);
  }, [notification, modal]);

  return null;
}
