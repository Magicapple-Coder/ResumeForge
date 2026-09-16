/**
 * 「引导对话已经给过了」这个事实的持久化记录。
 *
 * 自动创建引导对话只在用户第一次用助手时有意义。之前的判断只活在一次挂载里
 * （组件内 ref），于是用户把会话删光之后，每次重新进入助手页都会被再塞一条
 * ——等于把用户删掉的数据又造回来。要跨挂载、跨刷新记住这件事，只能落盘。
 */

const WELCOME_SHOWN_KEY = "resumeforge.assistant.welcome-shown";

/** 读不到 localStorage（隐私模式、存储被禁用）时按"没给过"处理，不阻断页面。 */
export function hasShownAssistantWelcome(): boolean {
  try {
    return window.localStorage.getItem(WELCOME_SHOWN_KEY) === "1";
  } catch {
    return false;
  }
}

/** 写不进去就退回"每次都问一次"的老行为，总好过让整个页面报错。 */
export function markAssistantWelcomeShown(): void {
  try {
    window.localStorage.setItem(WELCOME_SHOWN_KEY, "1");
  } catch {
    // 忽略：这只是"要不要再引导一次"的优化，不是功能本身。
  }
}
