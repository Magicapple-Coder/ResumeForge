import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// `findBy*` 的默认等待窗口只有 1 秒，而这些页面要挂载 antd 的整套组件、再等几个 mock 接口
// 依次 resolve；机器一忙就会在"还没渲染完"的时候超时，表现为随机失败（同一个文件里不同的用例
// 轮流失败）。vitest.config.ts 里把 testTimeout 提到 15 秒也是为这件事，但那只放宽了单个用例的
// 总时长，没有放宽断言自己的等待窗口。这里对齐两者：断言等应用稳定，而不是等一个固定的 1 秒。
configure({ asyncUtilTimeout: 5000 });

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
