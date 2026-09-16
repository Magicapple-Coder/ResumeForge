import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
// 路由表就在 App.tsx 里，读它的源码即可——再维护一份页面清单只会多一处会过期的真相。
import appSource from "../App.tsx?raw";
import UserGuideModal from "./UserGuideModal";
import { GUIDE_STEPS } from "./userGuideSteps";

afterEach(() => {
  cleanup();
  // Ant Design's exit motion is asynchronous; remove a portal left after a mocked close.
  document.body.innerHTML = "";
});

/** 按标题走到某一步：写死点几次“下一步”的话，插入一步就会连带改一堆断言。 */
function goToStep(title: string) {
  const index = GUIDE_STEPS.findIndex((step) => step.title === title);
  if (index < 0) throw new Error(`使用指南里没有「${title}」这一步`);
  for (let step = 0; step < index; step += 1) {
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
  }
}

describe("UserGuideModal", () => {
  it("walks through the workflow and can open the related page", () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();

    render(<UserGuideModal open onClose={onClose} onNavigate={onNavigate} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("选择预设或自定义模型")).toBeInTheDocument();
    expect(screen.getByText(/纯手动配置/)).toBeInTheDocument();

    goToStep("完善资料");
    expect(screen.getByText("建立你的事实资料库")).toBeInTheDocument();
    // 文档识别是用户看得见的能力，指南必须提到，否则用户不会想到可以传 PDF。
    expect(screen.getByText(/pdf\/docx 简历文档/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /前往我的资料/ }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledWith("/profile");
  });

  it("explains manual, pasted-text, screenshot and document job entry", () => {
    render(<UserGuideModal open onClose={vi.fn()} onNavigate={vi.fn()} />);

    goToStep("导入岗位");

    expect(screen.getByText("手动填写或粘贴招聘信息")).toBeInTheDocument();
    expect(screen.getByText(/粘贴完整招聘信息/)).toBeInTheDocument();
    expect(screen.getByText(/识别结果不会自动保存/)).toBeInTheDocument();
    expect(screen.getByText(/pdf\/docx 招聘文档都能识别/)).toBeInTheDocument();
  });

  it("says the assistant can change data but never delete it", () => {
    render(<UserGuideModal open onClose={vi.fn()} onNavigate={vi.fn()} />);

    goToStep("求职助手");

    expect(screen.getByText("让助手直接帮你处理数据")).toBeInTheDocument();
    expect(screen.getByText(/但它不会替你删除任何数据/)).toBeInTheDocument();
    expect(screen.getByText(/助手技能/)).toBeInTheDocument();
  });

  it("finishes by pointing at the data backup step", () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();
    render(<UserGuideModal open onClose={onClose} onNavigate={onNavigate} />);

    goToStep(GUIDE_STEPS[GUIDE_STEPS.length - 1].title);

    expect(screen.getByText("把数据带走，或换一份")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /前往设置/ }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledWith("/settings");
    // 最后一步用“开始使用”收尾，不再有“下一步”。
    expect(screen.queryByRole("button", { name: /下一步/ })).not.toBeInTheDocument();
  });

  it("supports closing the guide without navigation", () => {
    const onClose = vi.fn();
    render(<UserGuideModal open onClose={onClose} onNavigate={vi.fn()} />);

    fireEvent.click(screen.getAllByRole("button", { name: "稍后查看" })[0]);
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("GUIDE_STEPS", () => {
  function appRoutes(): string[] {
    return [...appSource.matchAll(/<Route\s+path="([^"]+)"/g)].map((match) => match[1]);
  }

  it("only points at pages that exist", () => {
    const routes = appRoutes();

    expect(routes.length).toBeGreaterThan(0);
    for (const step of GUIDE_STEPS) {
      expect(routes).toContain(step.path);
    }
  });

  it("has no duplicate titles and a full set of copy on every step", () => {
    // 标题是 Steps 的定位与测试的入口，重复会让两者都指错地方。
    expect(new Set(GUIDE_STEPS.map((step) => step.title)).size).toBe(GUIDE_STEPS.length);
    for (const step of GUIDE_STEPS) {
      expect(step.heading.length).toBeGreaterThan(0);
      expect(step.description.length).toBeGreaterThan(0);
      expect(step.points.length).toBeGreaterThan(0);
      expect(step.actionLabel.length).toBeGreaterThan(0);
    }
  });
});
