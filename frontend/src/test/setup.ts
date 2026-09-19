import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// `findBy*` 的默认等待窗口只有 1 秒，而这些页面要挂载 antd 的整套组件、再等几个 mock 接口
// 依次 resolve；机器一忙就会在"还没渲染完"的时候超时，表现为随机失败（同一个文件里不同的用例
// 轮流失败）。
//
// 15 秒这个值是按**全量并行时的实测**定的，不是拍脑袋：vitest 默认按 CPU 数开线程（本机 32 核
// → 30 多个 jsdom 实例抢 CPU），重页面（设置页六张卡 + 消息列表）单个用例实测要 8~12 秒，
// 5 秒必然在满负载下随机超时——这正是"单跑全过、全量随机挂 3 个"的来源。
//
// 上限刻意**低于** vitest.config.ts 的 `testTimeout: 30000`：断言窗口和用例总预算取同一个值的话，
// 一次真正的"元素找不到"要等满 30 秒才报出来，失败的反馈速度会明显变差。
configure({ asyncUtilTimeout: 15000 });

const jsdomGetComputedStyle = window.getComputedStyle.bind(window);
Object.defineProperty(window, "getComputedStyle", {
  configurable: true,
  value: (element: Element) => jsdomGetComputedStyle(element),
});

class ResizeObserverMock {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

Object.defineProperty(window, "ResizeObserver", {
  configurable: true,
  value: ResizeObserverMock,
});

// jsdom 没有实现对象 URL，而下载与打印都依赖它。
Object.defineProperty(URL, "createObjectURL", {
  configurable: true,
  writable: true,
  value: () => "blob:jsdom-object-url",
});

Object.defineProperty(URL, "revokeObjectURL", {
  configurable: true,
  writable: true,
  value: () => undefined,
});

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
