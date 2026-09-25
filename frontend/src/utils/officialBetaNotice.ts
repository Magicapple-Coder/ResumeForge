/**
 * 「官网采集还在打磨中」的提示状态。
 *
 * 这条提示存在的原因不是"新功能值得宣传"，而是**防止误会**：采集读不出某个站点时，
 * 用户很容易理解成"我自己填错了"或"这家公司没在招人"。所以第一次进这个页面必须说清
 * ——能力边界在哪、结论怎么读、后续会怎么处理。
 *
 * 两个刻意选择：
 * 1. 弹窗**一个浏览器只自动弹一次**（与首次使用引导同一套做法）。每次进页面都弹一遍
 *    会从"提醒"变成"骚扰"，而页面顶部那条常驻说明一直在，漏看也能补上。
 * 2. 标记写在 localStorage 而不是后端：它是"这台机器的这个人看过没有"，不该占用
 *    用户的数据表，也不该跟着数据备份走。
 */

const OFFICIAL_BETA_STORAGE_KEY = "resumeforge.official-beta-notice.seen";

function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "1";
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function getBrowserStorage(): StorageLike | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    return window.localStorage;
  } catch {
    // 隐私模式或浏览器策略可能禁用 localStorage；此时仍允许本次会话展示提示。
    return undefined;
  }
}

/** 原子地消费标记：返回"这次该自动弹窗吗"，并把已读写上。 */
export function consumeOfficialBetaNotice(
  storage: StorageLike | undefined = getBrowserStorage(),
): boolean {
  if (isDemoMode()) {
    // 演示站里不自动弹：访客是被官网的步骤引导带着看的，再叠一层弹窗会挡住演示内容。
    // 仍然写标记，避免他之后下载完整版在同一浏览器里被弹一次已经看过的东西。
    markOfficialBetaNoticeSeen(storage);
    return false;
  }
  if (!storage) return true;
  try {
    if (storage.getItem(OFFICIAL_BETA_STORAGE_KEY) === "1") return false;
    storage.setItem(OFFICIAL_BETA_STORAGE_KEY, "1");
    return true;
  } catch {
    return true;
  }
}

export function markOfficialBetaNoticeSeen(
  storage: StorageLike | undefined = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(OFFICIAL_BETA_STORAGE_KEY, "1");
  } catch {
    // 提示本身不应因为浏览器存储不可用而阻塞页面。
  }
}

export { OFFICIAL_BETA_STORAGE_KEY };
