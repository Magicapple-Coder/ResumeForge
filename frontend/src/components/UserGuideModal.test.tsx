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

    goToStep("完善资料与事实台账");
    expect(screen.getByText("建立你的事实资料库")).toBeInTheDocument();
    // 文档识别是用户看得见的能力，指南必须提到，否则用户不会想到可以传 PDF。
    expect(screen.getByText(/pdf\/docx 简历文档/)).toBeInTheDocument();
    // 事实台账是这一轮新增的用户可见能力：不说清楚，用户不会知道"哪些话能说"
    // 是在这里维护的，也就用不上"导出被拦下"那条保护。
    expect(screen.getAllByText(/事实台账/).length).toBeGreaterThan(0);
    // 用户得知道它在侧栏的哪儿，否则这一条等于没说。
    expect(screen.getByText(/侧栏「我的资料」之后/)).toBeInTheDocument();
    expect(screen.getByText(/只有标成「已确认」的条目/)).toBeInTheDocument();
    // 深挖是台账的延伸，入口在台账页里——不写清用户找不到。
    expect(screen.getByText(/拿去深挖/)).toBeInTheDocument();
    expect(screen.getByText(/在你看到问题\*\*之前\*\*就定下来/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /前往我的资料/ }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledWith("/profile");
  });

  it("explains manual entry, auto collection and the apply board on the job step", () => {
    render(<UserGuideModal open onClose={vi.fn()} onNavigate={vi.fn()} />);

    goToStep("导入岗位与投递");

    expect(screen.getByText("手动录入、自动采集，再到投递台投出去")).toBeInTheDocument();
    expect(screen.getByText(/识别结果不会自动保存/)).toBeInTheDocument();
    expect(screen.getByText(/pdf\/docx 招聘文档都能识别/)).toBeInTheDocument();
    // 新增能力必须在指南里说出来，否则用户不知道可以用——这是本轮扩写这一步的全部理由。
    expect(screen.getByText(/匹配度分析/)).toBeInTheDocument();
    expect(screen.getByText(/投递专用浏览器/)).toBeInTheDocument();
    expect(screen.getByText(/未生效/)).toBeInTheDocument();
  });

  it("explains how to track progress after applying", () => {
    render(<UserGuideModal open onClose={vi.fn()} onNavigate={vi.fn()} />);

    goToStep("跟进求职进度");

    expect(screen.getByText("投出去之后，对方走到哪一步了")).toBeInTheDocument();
    // 用户最需要知道的是"自动回执不会被当成面试"和"状态只会前进"——
    // 这两条不知道，就会误信一个错的进度。
    expect(screen.getByText(/不会被读成面试或 Offer/)).toBeInTheDocument();
    expect(screen.getByText(/状态只会前进/)).toBeInTheDocument();
    // 预览这一步是这个功能的信任基础，必须说出来。
    expect(screen.getByText(/先给你看会发生什么/)).toBeInTheDocument();
  });

  it("explains the layout diagnosis and auto-fit on the resume step", () => {
    render(<UserGuideModal open onClose={vi.fn()} onNavigate={vi.fn()} />);

    goToStep("制作简历");

    // 版式这块最容易被误以为是"猜的"，所以要说明它有明确的判断依据与顺序。
    expect(screen.getByText(/版面诊断/)).toBeInTheDocument();
    expect(screen.getByText(/占了多少|占了页面/)).toBeInTheDocument();
    expect(screen.getByText(/够放下就停/)).toBeInTheDocument();
    expect(screen.getByText(/12px/)).toBeInTheDocument();
  });

  it("says the assistant can change data but never delete it", () => {
    render(<UserGuideModal open onClose={vi.fn()} onNavigate={vi.fn()} />);

    goToStep("求职助手");

    expect(screen.getByText("让助手直接帮你处理数据")).toBeInTheDocument();
    expect(screen.getByText(/但它不会替你删除任何数据/)).toBeInTheDocument();
    // 技能在助手页的入口（输入框下方工具条）和新建/编辑入口（工作台）都要指明。
    // 侧栏那一项已经叫「工作台」了（技能 + 简历模板两页），指南里不能再写旧名字。
    expect(screen.getByText(/「技能」按钮可以直接开关/)).toBeInTheDocument();
    expect(screen.getByText(/工作台 → 助手技能/)).toBeInTheDocument();
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
