/**
 * postMessage 桥的测试。
 *
 * 重点在**安全校验**：不校验来源或不做路由白名单，等于允许任意页面
 * 把一个字符串塞进本应用的路由。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEMO_ROUTES, installDemoBridge, parseDemoMessage } from "./demoBridge";
import { MENU_ITEMS } from "../App";

const ORIGIN = "https://magicapple123.github.io";

describe("parseDemoMessage 的来源校验", () => {
  it("官网来源 + 合法路由 → 通过", () => {
    expect(parseDemoMessage({ type: "rf-demo:navigate", path: "/jobs" }, ORIGIN)).toEqual({
      type: "rf-demo:navigate",
      path: "/jobs",
    });
  });

  it("未知来源一律拒绝", () => {
    expect(
      parseDemoMessage({ type: "rf-demo:navigate", path: "/jobs" }, "https://evil.example"),
    ).toBe(null);
  });

  it("消息类型不对时拒绝", () => {
    expect(parseDemoMessage({ type: "other", path: "/jobs" }, ORIGIN)).toBeNull();
  });

  it("路由不在白名单时拒绝（挡住任意外部字符串进路由）", () => {
    expect(parseDemoMessage({ type: "rf-demo:navigate", path: "/admin" }, ORIGIN)).toBeNull();
    expect(
      parseDemoMessage({ type: "rf-demo:navigate", path: "https://x.com" }, ORIGIN),
    ).toBeNull();
    expect(
      parseDemoMessage({ type: "rf-demo:navigate", path: "/jobs/../../../etc" }, ORIGIN),
    ).toBeNull();
  });

  it("path 不是字符串时拒绝", () => {
    expect(parseDemoMessage({ type: "rf-demo:navigate", path: 42 }, ORIGIN)).toBeNull();
  });

  it("非对象载荷不抛错", () => {
    expect(parseDemoMessage(null, ORIGIN)).toBeNull();
    expect(parseDemoMessage("rf-demo:navigate", ORIGIN)).toBeNull();
  });
});

describe("DEMO_ROUTES 与 App 路由保持一致", () => {
  it("覆盖 MENU_ITEMS 的每一条", () => {
    const routes = DEMO_ROUTES as readonly string[];
    for (const item of MENU_ITEMS) {
      expect(routes, `白名单缺少菜单路由 ${item.key}`).toContain(item.key);
    }
  });

  it("没有多余项（避免白名单指向已删除的页面）", () => {
    const menuKeys = MENU_ITEMS.map((item) => item.key);
    for (const route of DEMO_ROUTES) {
      expect(menuKeys, `白名单里的 ${route} 不在菜单里`).toContain(route);
    }
  });
});

describe("installDemoBridge", () => {
  let uninstall: (() => void) | undefined;
  let parentDescriptor: PropertyDescriptor | undefined;

  /**
   * jsdom 里 `window.parent === window`，桥会据此判定"不在 iframe 里"而直接返回。
   * 用 `Object.defineProperty` 造一个不同的 parent，才能走到真正的监听逻辑。
   */
  function pretendEmbedded() {
    parentDescriptor = Object.getOwnPropertyDescriptor(window, "parent");
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: { postMessage: () => {} },
    });
  }

  afterEach(() => {
    uninstall?.();
    uninstall = undefined;
    if (parentDescriptor) {
      Object.defineProperty(window, "parent", parentDescriptor);
      parentDescriptor = undefined;
    } else {
      delete (window as unknown as Record<string, unknown>).parent;
    }
  });

  it("不在 iframe 里时不注册监听（独立打开演示站的场景）", () => {
    const navigate = vi.fn();
    uninstall = installDemoBridge(navigate);
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "rf-demo:navigate", path: "/claims" },
        origin: ORIGIN,
      }),
    );
    expect(navigate).not.toHaveBeenCalled();
  });

  it("收到合法指令时调用 navigate", () => {
    pretendEmbedded();
    const navigate = vi.fn();
    uninstall = installDemoBridge(navigate);
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "rf-demo:navigate", path: "/claims" },
        origin: ORIGIN,
      }),
    );
    expect(navigate).toHaveBeenCalledWith("/claims");
  });

  it("来源不合法时不调用 navigate", () => {
    pretendEmbedded();
    const navigate = vi.fn();
    uninstall = installDemoBridge(navigate);
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "rf-demo:navigate", path: "/claims" },
        origin: "https://evil.example",
      }),
    );
    expect(navigate).not.toHaveBeenCalled();
  });

  it("卸载后不再响应", () => {
    pretendEmbedded();
    const navigate = vi.fn();
    const undo = installDemoBridge(navigate);
    undo();
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "rf-demo:navigate", path: "/claims" },
        origin: ORIGIN,
      }),
    );
    expect(navigate).not.toHaveBeenCalled();
  });
});
