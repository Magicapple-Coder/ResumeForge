/**
 * 官网与演示实例之间的 postMessage 桥。
 *
 * 演示实例被官网 `demo.html` 用 iframe 内嵌，两个源不同，官网无法直接操作
 * 实例内部的路由。官网点「步骤 2：岗位与匹配度分析」时，需要实例自己跳过去——
 * 这条消息就是那个动作。
 *
 * ## 安全边界
 *
 * 校验两个方向：
 *   1. **发送方源**必须是官网域名（`ALLOWED_PARENTS`）。不校验的话，任何页面
 *      都能把这个实例嵌进自己的 iframe 里拿它当跳板（虽然演示站没有敏感数据，
 *      但没有理由接受任意来源的导航指令）。
 *   2. **消息形状**必须是 `{type: "rf-demo:navigate", path: string}`，
 *      且 `path` 必须命中本应用真实存在的路由白名单——直接把外部字符串
 *      交给 `navigate()` 等于允许别人控制你的路由，白名单是廉价的兜底。
 *
 * 独立打开（不在 iframe 里）时本模块不做任何事：`window.parent === window`。
 */

/**
 * 允许发指令的父页面源。
 *
 * 默认只认官网的正式域名。本地联调时把官网的地址加到
 * `frontend/.env.demo.local` 的 `VITE_DEMO_PARENT_ORIGINS`（该文件在
 * `.gitignore` 里），**不写死在代码里**——把 localhost 编进正式产物
 * 等于永久放宽一个来源。
 */
const DEFAULT_PARENTS = ["https://magicapple123.github.io"];

function allowedParents(): string[] {
  const extra = (import.meta.env.VITE_DEMO_PARENT_ORIGINS || "").trim();
  if (!extra) return DEFAULT_PARENTS;
  return [
    ...DEFAULT_PARENTS,
    ...extra
      .split(",")
      .map((item: string) => item.trim())
      .filter(Boolean),
  ];
}

/**
 * 可跳转的路由白名单。
 *
 * 与 `App.tsx` 的 `MENU_ITEMS` 保持一致，但**刻意不 import 它**：
 * 那个模块会连带引入 antd 图标与整棵路由树，为了几个字符串把首屏依赖拖进来
 * 不划算。新增页面时同步这里即可——`demoBridge.test.ts` 会对照 `MENU_ITEMS`
 * 做双向断言，漏改会红。
 */
export const DEMO_ROUTES = [
  "/",
  "/jobs",
  "/favorites",
  "/resumes",
  "/apply",
  "/tracker",
  "/analytics",
  "/interview",
  "/assistant",
  "/profile",
  "/materials",
  "/knowledge",
  "/skills",
  "/claims",
  "/trash",
  "/settings",
] as const;

export interface DemoNavigateMessage {
  type: "rf-demo:navigate";
  path: string;
}

/** 校验并解析一条外来消息；不合法返回 null。 */
export function parseDemoMessage(data: unknown, origin: string): DemoNavigateMessage | null {
  if (!allowedParents().includes(origin)) return null;
  if (!data || typeof data !== "object") return null;
  const candidate = data as Record<string, unknown>;
  if (candidate.type !== "rf-demo:navigate") return null;
  const path = candidate.path;
  if (typeof path !== "string") return null;
  if (!(DEMO_ROUTES as readonly string[]).includes(path)) return null;
  return { type: "rf-demo:navigate", path };
}

/**
 * 挂上监听。返回卸载函数。
 *
 * `navigate` 由调用方注入（`main.tsx` 里用 `BrowserRouter` 的实例），
 * 这样本模块不依赖 react-router，测试里也只需要传一个 spy。
 */
export function installDemoBridge(navigate: (path: string) => void): () => void {
  // 不在 iframe 里（用户直接打开了演示站）就没有父页面要通信。
  if (typeof window === "undefined" || window.parent === window) return () => {};

  const handler = (event: MessageEvent) => {
    const message = parseDemoMessage(event.data, event.origin);
    if (!message) return;
    navigate(message.path);
  };

  window.addEventListener("message", handler);
  return () => window.removeEventListener("message", handler);
}
