import { App as AntdApp, ConfigProvider } from "antd";
import NotifyHostBridge from "./components/NotifyHostBridge";
import zhCN from "antd/locale/zh_CN";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import AppErrorBoundary from "./components/AppErrorBoundary";
import "./index.css";

/**
 * 在线体验模式：先装好请求拦截层，再挂载应用。
 *
 * 这一段是**静态判断 + 动态 import**，不是普通的条件渲染：`VITE_DEMO_MODE` 只在
 * 演示构建里为 "1"，普通构建时 `if` 恒假，打包器会把整个 `./demo/*` 子树摇掉，
 * 主发行包里不会多出一行演示代码，也不会多出几百 KB 的快照引用。
 *
 * 顺序不能反：首屏的几个请求（`/api/stats`、`/api/reminders/upcoming`…）在
 * `App` 挂载时立刻发出，拦截层必须在那一刻之前就位，否则会打到不存在的后端上。
 */
async function start() {
  if (import.meta.env.VITE_DEMO_MODE === "1") {
    const { bootstrapDemoMode } = await import("./demo/demoBootstrap");
    try {
      await bootstrapDemoMode();
    } catch {
      // `bootstrapDemoMode` 内部已经装了拦截层并打印了原因；这里继续挂载，
      // 让页面走各自的空态/错误态，用户看到的是"演示数据未就绪"而不是白屏。
    }
  }

  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <ConfigProvider
        locale={zhCN}
        theme={{ token: { colorPrimary: "#16365c", borderRadius: 6 } }}
        // 弹窗内容在**卡片自己身上**滚动，而不是让整页滚动。
        // antd 默认把 Modal 当作文档流里的普通元素（它只是 position: fixed 的遮罩），
        // 卡片一高，撑大的就是 <body>——于是滚动条跑到整个窗口的右边，用户得先滑页面
        // 才能看到卡片下半部分，卡片自己的右上角也没有滚动条。挂到 body 上之后，
        // 卡片脱离文档流，页面高度不受影响，滚动条落在卡片右侧。
        getPopupContainer={() => document.body}
      >
        {/* AntdApp 提供上下文版 message/modal，兼容主题 */}
        <AntdApp>
          {/* 把 AntD 的通知/弹窗实例交给 utils/taskNotify：生成完成后"弹窗 + 提示声"这件事
              需要一个能在任何模块里调用的出口，而 useApp() 只能在组件里用。 */}
          <NotifyHostBridge />
          <AppErrorBoundary>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </AppErrorBoundary>
        </AntdApp>
      </ConfigProvider>
    </React.StrictMode>,
  );
}

void start();
