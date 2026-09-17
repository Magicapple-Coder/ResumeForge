/** 应用生命周期接口。 */
import { request } from "./client";

export interface ShutdownResult {
  status: string;
  message: string;
}

/**
 * 退出应用（结束后端进程）。
 *
 * 只有运行后端的本机能调用——局域网里的页面会收到 403。前端页面本身不需要"退出"：
 * 后端一停，所有数据请求就都不再可用，界面会进入"已退出"状态。
 */
export function shutdownApp(): Promise<ShutdownResult> {
  return request("/system/shutdown", { method: "POST" });
}
