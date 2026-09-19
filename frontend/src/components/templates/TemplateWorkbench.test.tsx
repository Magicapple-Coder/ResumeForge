/**
 * 工作台「找求职助手制作」入口：把用户带到助手页并预填一句提问。
 *
 * 这条链路横跨两个页面（工作台 → `/assistant?ask=`），只靠代码审阅很容易在重构时被
 * 悄悄改坏（改了 query 参数名、忘了带上下文、或把行内入口也给了样式模板），所以在这里
 * 钉住跳转 URL 与"只有格式模板行才提供让助手改"这两件事。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TEMPLATE_CATALOG } from "../../test/resumeFixtures";
import type { ResumeTemplateDetail } from "../../types";
import TemplateWorkbench from "./TemplateWorkbench";

// 只拦真正会发请求的两个模块：
// - `api/resumes` 提供内置目录与缩略图渲染；
// - `api/resumeTemplates` 提供自制模板列表（点击/删除/复制在内置目录测试里不需要）。
const resumeApiMocks = vi.hoisted(() => ({
  fetchResumeTemplates: vi.fn(),
  previewResumeTemplate: vi.fn(),
}));
vi.mock("../../api/resumes", () => resumeApiMocks);

const templateApiMocks = vi.hoisted(() => ({
  listResumeTemplates: vi.fn(),
  deleteResumeTemplate: vi.fn(),
  fetchBuiltinTemplateSource: vi.fn(),
}));
vi.mock("../../api/resumeTemplates", () => templateApiMocks);

function templateDetail(overrides: Partial<ResumeTemplateDetail>): ResumeTemplateDetail {
  return {
    id: 1,
    name: "模板",
    kind: "format",
    description: "",
    enabled: true,
    source_name: "",
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    html: "",
    config: {},
    ...overrides,
  };
}

/** 路径 + 查询串探针，用来断言"点了之后去了哪"。 */
function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{`${location.pathname}${location.search}`}</span>;
}

function renderWorkbench() {
  return render(
    <MemoryRouter>
      <AntdApp>
        <TemplateWorkbench />
        <LocationProbe />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  resumeApiMocks.fetchResumeTemplates.mockReset().mockResolvedValue(TEMPLATE_CATALOG);
  resumeApiMocks.previewResumeTemplate.mockReset().mockResolvedValue("<html></html>");
  templateApiMocks.listResumeTemplates.mockReset().mockResolvedValue([]);
  templateApiMocks.deleteResumeTemplate.mockReset();
  templateApiMocks.fetchBuiltinTemplateSource.mockReset();
});

afterEach(cleanup);

describe("TemplateWorkbench 的求职助手入口", () => {
  it("「找求职助手制作」跳转时带上编码后的预填提问", async () => {
    renderWorkbench();

    // 图标会贡献一个可访问名片段，所以按子串匹配按钮名。
    fireEvent.click(await screen.findByRole("button", { name: /找求职助手制作/ }));

    await waitFor(() =>
      expect(screen.getByTestId("location").textContent).toBe(
        `/assistant?ask=${encodeURIComponent("帮我新建一个格式模板：")}`,
      ),
    );
  });

  it("格式模板行提供「找助手改这个模板」，并带上模板名", async () => {
    templateApiMocks.listResumeTemplates.mockResolvedValue([
      templateDetail({ id: 7, name: "压页版式", kind: "format" }),
    ]);
    renderWorkbench();
    await screen.findByText("压页版式");

    fireEvent.click(screen.getAllByRole("button", { name: "更多操作" })[0]);
    fireEvent.click(await screen.findByText("找助手改这个模板"));

    await waitFor(() =>
      expect(screen.getByTestId("location").textContent).toBe(
        `/assistant?ask=${encodeURIComponent("帮我调整格式模板「压页版式」：")}`,
      ),
    );
  });

  it("样式模板行不提供「找助手改这个模板」——助手不生成 HTML", async () => {
    templateApiMocks.listResumeTemplates.mockResolvedValue([
      templateDetail({ id: 3, name: "我的样式", kind: "style", html: "<html></html>" }),
    ]);
    renderWorkbench();
    await screen.findByText("我的样式");

    fireEvent.click(screen.getAllByRole("button", { name: "更多操作" })[0]);
    // 菜单确实打开了（预览/编辑/删除都在），但唯独没有交给助手的那一项。
    await screen.findByText("预览效果");
    expect(screen.queryByText("找助手改这个模板")).not.toBeInTheDocument();
  });
});
