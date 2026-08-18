import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

vi.mock("./pages/HomePage", () => ({ default: () => <div>首页内容</div> }));
vi.mock("./pages/JobsPage", () => ({ default: () => <div>岗位广场内容</div> }));
vi.mock("./pages/ProfilePage", () => ({ default: () => <div>我的资料内容</div> }));
vi.mock("./pages/ResumesPage", () => ({ default: () => <div>简历中心内容</div> }));
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
