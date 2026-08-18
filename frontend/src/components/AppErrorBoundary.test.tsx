import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AppErrorBoundary from "./AppErrorBoundary";

function BrokenView(): never {
  throw new Error("render failed");
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AppErrorBoundary", () => {
  it("shows a recoverable fallback when a child crashes", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const reload = vi.fn();
    const preventJsdomReport = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", preventJsdomReport);

    try {
      render(
        <AppErrorBoundary onReload={reload}>
          <BrokenView />
        </AppErrorBoundary>,
      );
    } finally {
      window.removeEventListener("error", preventJsdomReport);
    }

    expect(screen.getByText("页面暂时无法显示")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(reload).toHaveBeenCalledOnce();
  });
});
