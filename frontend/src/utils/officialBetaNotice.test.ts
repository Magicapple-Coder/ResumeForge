/** 「官网采集还在打磨中」提示：一个浏览器只自动弹一次，且演示站不弹。 */

import { afterEach, describe, expect, it } from "vitest";
import {
  OFFICIAL_BETA_STORAGE_KEY,
  consumeOfficialBetaNotice,
  markOfficialBetaNoticeSeen,
} from "./officialBetaNotice";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => {
      data[key] = value;
    },
    dump: () => data,
  };
}

afterEach(() => {
  window.localStorage.clear();
});

describe("consumeOfficialBetaNotice", () => {
  it("第一次消费返回 true 并写标记，第二次返回 false", () => {
    const storage = memoryStorage();
    expect(consumeOfficialBetaNotice(storage)).toBe(true);
    expect(storage.dump()[OFFICIAL_BETA_STORAGE_KEY]).toBe("1");
    expect(consumeOfficialBetaNotice(storage)).toBe(false);
  });

  it("已经看过的人不再被弹", () => {
    const storage = memoryStorage({ [OFFICIAL_BETA_STORAGE_KEY]: "1" });
    expect(consumeOfficialBetaNotice(storage)).toBe(false);
  });

  it("浏览器存储不可用时仍然弹（提示比记住重要）", () => {
    expect(consumeOfficialBetaNotice(undefined)).toBe(true);
  });

  it("存储项被清空后重新会弹一次（用户清缓存等价于重新开始）", () => {
    const storage = memoryStorage();
    consumeOfficialBetaNotice(storage);
    storage.setItem(OFFICIAL_BETA_STORAGE_KEY, "");
    expect(consumeOfficialBetaNotice(storage)).toBe(true);
  });

  it("markOfficialBetaNoticeSeen 单独可用且不影响已有标记", () => {
    const storage = memoryStorage();
    markOfficialBetaNoticeSeen(storage);
    expect(storage.dump()[OFFICIAL_BETA_STORAGE_KEY]).toBe("1");
    expect(consumeOfficialBetaNotice(storage)).toBe(false);
  });
});
