/**
 * 退出应用：结束后端进程，并把页面切成"已退出"状态。
 *
 * 为什么由后端负责退出：前端只是浏览器里的一个页面，关掉它并不会停止后端服务——用户
 * 真正想停掉的是那个占用端口、还在跑数据库的进程。所以这里调用 `/api/system/shutdown`，
 * 后端自己优雅退出；页面随后进入不可用状态并提示如何重新启动。
 */
import { LogoutOutlined } from "@ant-design/icons";
import { App, Button, Result, Tooltip } from "antd";
import { useState } from "react";
import { shutdownApp } from "../../api/system";

export default function ExitAppButton() {
  const { modal, message } = App.useApp();
  const [exited, setExited] = useState(false);
  const [exiting, setExiting] = useState(false);

  const exit = () => {
    modal.confirm({
      title: "退出简历通？",
      content:
        "后端服务会立即停止，当前页面上的查询与生成都将不可用。下次使用请在项目目录重新运行 start.cmd。",
      okText: "退出",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        setExiting(true);
        try {
          const result = await shutdownApp();
          message.success(result.message || "应用正在退出");
        } catch (error) {
          message.error(
            error instanceof Error
              ? `${error.message}（也可以直接关闭后端窗口）`
              : "退出失败，也可以直接关闭后端窗口",
          );
          setExiting(false);
          // 抛出让 Modal 保持打开：失败时用户需要看到发生了什么。
          throw error;
        }
        setExited(true);
        // 多数浏览器只允许脚本关闭自己打开的窗口，被拒绝也无妨——页面上已有明确提示。
        window.setTimeout(() => window.close(), 600);
      },
    });
  };

  if (exited) {
    return (
      <div className="app-exited-overlay">
        <Result
          status="success"
          title="简历通已退出"
          subTitle="后端服务已停止。要再次使用，请在项目目录运行 start.cmd，然后刷新此页面。"
        />
      </div>
    );
  }

  return (
    <Tooltip title="退出应用（停止后端服务）">
      <Button
        className="app-exit-button"
        type="text"
        size="small"
        icon={<LogoutOutlined />}
        loading={exiting}
        onClick={exit}
        aria-label="退出应用"
      >
        <span className="app-exit-label">退出</span>
      </Button>
    </Tooltip>
  );
}
