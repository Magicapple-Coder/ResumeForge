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
    expect(screen.getByText("选择预设或自定义模型")).toBeInTheDocument();
    expect(screen.getByText(/自定义模型（OpenAI 兼容）/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    expect(screen.getByText("建立你的事实资料库")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /前往我的资料/ }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledWith("/profile");
  });

  it("explains manual and pasted-text job entry", () => {
    render(<UserGuideModal open onClose={vi.fn()} onNavigate={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    expect(screen.getByText("手动填写或粘贴招聘信息")).toBeInTheDocument();
    expect(screen.getByText(/粘贴完整招聘信息/)).toBeInTheDocument();
    expect(screen.getByText(/识别结果不会自动保存/)).toBeInTheDocument();
  });

  it("finishes with project management and the assistant", () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();
    render(<UserGuideModal open onClose={onClose} onNavigate={onNavigate} />);

    for (let index = 0; index < 4; index += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }

    expect(screen.getByText("串联岗位、简历和求职准备")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /打开求职助手/ }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledWith("/assistant");
  });

  it("supports closing the guide without navigation", () => {
    const onClose = vi.fn();
    render(<UserGuideModal open onClose={onClose} onNavigate={vi.fn()} />);

    fireEvent.click(screen.getAllByRole("button", { name: "稍后查看" })[0]);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
