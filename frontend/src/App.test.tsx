import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { APP_NAME, GITHUB_REPO } from "./config";

vi.mock("./pages/HomePage", () => ({ default: () => <div>首页内容</div> }));
vi.mock("./pages/JobsPage", () => ({ default: () => <div>岗位广场内容</div> }));
vi.mock("./pages/ProfilePage", () => ({ default: () => <div>我的资料内容</div> }));
vi.mock("./pages/ResumesPage", () => ({ default: () => <div>简历中心内容</div> }));
vi.mock("./pages/FavoritesPage", () => ({ default: () => <div>收藏夹内容</div> }));
vi.mock("./pages/AssistantPage", () => ({ default: () => <div>求职助手内容</div> }));
vi.mock("./pages/SettingsPage", () => ({ default: () => <div>设置内容</div> }));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.body.innerHTML = "";
});

describe("first-visit guide", () => {
  it("opens automatically once and remains available from the sidebar", async () => {
    const firstRender = render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("dialog", { name: "欢迎使用简历通" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "稍后查看" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    firstRender.unmount();

    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    await screen.findByText("首页内容");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "使用指南" }));
    expect(await screen.findByRole("dialog", { name: "欢迎使用简历通" })).toBeInTheDocument();
  });
});

describe("application navigation", () => {
  it("opens the favorites and assistant pages from the sidebar", async () => {
    window.localStorage.setItem("resumeforge.user-guide.seen", "1");
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText("收藏夹"));
    expect(await screen.findByText("收藏夹内容")).toBeInTheDocument();

    fireEvent.click(screen.getByText("求职助手"));
    expect(await screen.findByText("求职助手内容")).toBeInTheDocument();
  });

  it("keeps the open-source link in the header actions, not in the sidebar footer", async () => {
    window.localStorage.setItem("resumeforge.user-guide.seen", "1");
    const { container } = render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    // 入口走过三个位置：页头右上角的一行文字（太抢注意力）→ 侧栏左下角图标（要找到底部）
    // → 页头右上角图标（与「退出」并排，符合"关于本项目"这类入口的习惯）。
    // 这条断言钉住的是**位置**，不是"存在"——只断言存在的话，挪到哪里都能过。
    const headerActions = container.querySelector(".app-header-actions");
    expect(headerActions).not.toBeNull();
    const repoLink = headerActions?.querySelector(".app-repo-button");
    expect(repoLink).not.toBeNull();
    expect(repoLink).toHaveAttribute("href", GITHUB_REPO);
    expect(repoLink).toHaveAttribute("aria-label", `在 GitHub 上查看 ${APP_NAME} 源码`);
    // 页头里必须和「退出」并排，且页脚不再有第二个源码入口。
    expect(headerActions?.textContent).toContain("退出");
    expect(container.querySelector(".app-sider-footer .app-repo-button")).toBeNull();
  });
});
