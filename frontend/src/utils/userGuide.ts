/** 首次使用引导只保存在当前浏览器，不写入后端或用户业务数据。 */
export const USER_GUIDE_STORAGE_KEY = "resumeforge.user-guide.seen";

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
  if (!shouldShowUserGuide(storage)) return false;
  markUserGuideSeen(storage);
  return true;
}
