import { App as AntdApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import AppErrorBoundary from "./components/AppErrorBoundary";
import "./index.css";

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
        <AppErrorBoundary>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AppErrorBoundary>
      </AntdApp>
    </ConfigProvider>
  </React.StrictMode>,
);
