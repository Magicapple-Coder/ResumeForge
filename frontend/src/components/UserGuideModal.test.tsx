import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import UserGuideModal from "./UserGuideModal";

afterEach(() => {
  cleanup();
  // Ant Design's exit motion is asynchronous; remove a portal left after a mocked close.
  document.body.innerHTML = "";
});

describe("UserGuideModal", () => {
  it("walks through the workflow and can open the related page", () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();

    render(<UserGuideModal open onClose={onClose} onNavigate={onNavigate} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("先决定是否使用 AI")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    expect(screen.getByText("建立你的事实资料库")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /前往我的资料/ }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledWith("/profile");
  });

  it("supports closing the guide without navigation", () => {
    const onClose = vi.fn();
    render(<UserGuideModal open onClose={onClose} onNavigate={vi.fn()} />);

    fireEvent.click(screen.getAllByRole("button", { name: "稍后查看" })[0]);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
