import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AppErrorBoundary from "./AppErrorBoundary";

function BrokenView(): never {
  throw new Error("render failed");
}

/** 懒加载的页面代码没取到时的真实报错文案（Chromium）。 */
function ModuleLoadFailureView(): never {
  throw new TypeError(
    "Failed to fetch dynamically imported module: http://127.0.0.1:5173/src/pages/ApplyPage.tsx",
  );
}

/** 渲染一个必然抛错的子树，并压掉 React/jsdom 转发到控制台与 window 的报错。
 *
 * 参数必须是**组件**而不是调用结果：`child()` 在测试自己的作用域里求值的话，
 * 异常根本不会经过错误边界。
 */
function renderBroken(View: () => never, onReload = vi.fn()): ReturnType<typeof vi.fn> {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const preventJsdomReport = (event: ErrorEvent) => event.preventDefault();
  window.addEventListener("error", preventJsdomReport);
  try {
    render(
      <AppErrorBoundary onReload={onReload}>
        <View />
      </AppErrorBoundary>,
    );
  } finally {
    window.removeEventListener("error", preventJsdomReport);
  }
  return onReload;
}

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("AppErrorBoundary", () => {
  it("shows a recoverable fallback when a child crashes", () => {
    const reload = renderBroken(BrokenView);

    expect(screen.getByText("页面暂时无法显示")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(reload).toHaveBeenCalledOnce();
  });

  it("把原始报错显示出来，便于定位而不是只给一句「运行时异常」", () => {
    renderBroken(BrokenView);

    expect(screen.getByText(/原因：render failed/)).toBeInTheDocument();
  });

  it("动态 import 失败时给出「重启 dev server」的可执行指引", () => {
    renderBroken(ModuleLoadFailureView);

    // 这一类刷新无用（是 dev server 缓存了旧模块解析），所以不能只说"重新加载"。
    expect(screen.getByText("页面代码没能加载完整")).toBeInTheDocument();
    expect(screen.getByText(/重启前端开发服务器/)).toBeInTheDocument();
    expect(screen.queryByText("页面暂时无法显示")).not.toBeInTheDocument();
  });
});
