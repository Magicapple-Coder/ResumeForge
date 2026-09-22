/**
 * 在线体验模式的启动入口。
 *
 * `main.tsx` 在 `import.meta.env.VITE_DEMO_MODE === "1"` 时才动态引入本文件，
 * 普通构建会被 tree-shake 掉，主发行包里不含演示代码。
 *
 * 顺序很重要：**先取到快照、装好拦截层，再挂载 React**。反过来的话，
 * 首屏那几个请求会在拦截层就位之前发出去，打到并不存在的后端上，
 * 用户看到的是"连接失败"而不是演示数据。
 */
import { installDemoFetch, loadDemoData } from "./demoFetch";

/** Pages 部署在子路径下，`base: "./"` 让相对路径跟着产物根走。 */
const SNAPSHOT_URL = new URL("demo-data/api-snapshot.json", document.baseURI).href;
const AI_REPLIES_URL = new URL("demo-data/ai-replies.json", document.baseURI).href;

export async function bootstrapDemoMode(): Promise<void> {
  try {
    await loadDemoData({ snapshotUrl: SNAPSHOT_URL, aiRepliesUrl: AI_REPLIES_URL });
    installDemoFetch();
  } catch (err) {
    // 快照缺失时仍然装拦截层：让页面统一报"演示数据未就绪"，
    // 而不是每个页面各自抛出网络错误。
    installDemoFetch();
    console.error("[demo] 演示数据加载失败：", err);
    throw err;
  }
}
