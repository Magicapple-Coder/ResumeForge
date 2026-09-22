/** 首次使用引导只保存在当前浏览器，不写入后端或用户业务数据。 */
export const USER_GUIDE_STORAGE_KEY = "resumeforge.user-guide.seen";

/**
 * 在线体验模式下不自动弹引导。
 *
 * 演示实例是嵌在官网里的，访客是被官网的步骤引导带着看的；此时再叠一层
 * 本站的向导弹窗，既盖住演示内容，又和官网的引导重复。注意只关掉**自动弹出**，
 * 侧栏的「使用指南」按钮仍然可用——访客想看随时能看。
 */
function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "1";
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function getBrowserStorage(): StorageLike | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    return window.localStorage;
  } catch {
    // 隐私模式或浏览器策略可能禁用 localStorage；此时仍允许本次会话展示引导。
    return undefined;
  }
}

export function shouldShowUserGuide(
  storage: StorageLike | undefined = getBrowserStorage(),
): boolean {
  if (!storage) return true;
  try {
    return storage.getItem(USER_GUIDE_STORAGE_KEY) !== "1";
  } catch {
    return true;
  }
}

export function markUserGuideSeen(storage: StorageLike | undefined = getBrowserStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(USER_GUIDE_STORAGE_KEY, "1");
  } catch {
    // 引导本身不应因为浏览器存储不可用而阻塞应用。
  }
}

/** 原子地消费首次访问标记，避免 React StrictMode 重复 effect 导致状态反复切换。 */
export function consumeFirstVisitGuide(
  storage: StorageLike | undefined = getBrowserStorage(),
): boolean {
  if (isDemoMode()) {
    // 也把标记写上：访客之后下载完整版、在同一浏览器打开时不该再被弹一次
    // 他自己在演示站里已经看过的指南——演示站和完整版同源的情况下会共用这份存储。
    markUserGuideSeen(storage);
    return false;
  }
  if (!shouldShowUserGuide(storage)) return false;
  markUserGuideSeen(storage);
  return true;
}
