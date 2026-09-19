/**
 * 知识库页面：列表渲染、筛选、新建、编辑、删除确认与 Markdown 预览。
 *
 * 删除走 RowActions 的「更多」菜单 + 二次确认（modal.confirm），编辑/删除用图标按钮而非裸文字。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Knowledge } from "../types";
import KnowledgePage from "./KnowledgePage";

const apiMocks = vi.hoisted(() => ({
  listKnowledge: vi.fn(),
  listKnowledgeCategories: vi.fn(),
  getKnowledge: vi.fn(),
  createKnowledge: vi.fn(),
  updateKnowledge: vi.fn(),
  deleteKnowledge: vi.fn(),
}));

vi.mock("../api/knowledge", () => apiMocks);

function makeKnowledge(overrides: Partial<Knowledge> = {}): Knowledge {
  return {
    id: 1,
    title: "STAR 法则",
    category: "简历技巧",
    tags: ["简历", "STAR"],
    content: "# 核心要点\n\n用 **STAR 法则** 组织经历，给出**量化结果**。",
    source: "手动录入",
    created_at: "2026-09-18T00:00:00",
    updated_at: "2026-09-18T00:00:00",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AntdApp>
        <KnowledgePage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  for (const mock of Object.values(apiMocks)) mock.mockReset();
  apiMocks.listKnowledge.mockResolvedValue([makeKnowledge()]);
  apiMocks.listKnowledgeCategories.mockResolvedValue(["面经", "简历技巧", "求职策略"]);
  apiMocks.createKnowledge.mockImplementation(async (payload) =>
    makeKnowledge({ id: 2, ...payload, tags: payload.tags }),
  );
  apiMocks.updateKnowledge.mockImplementation(async (id, payload) => makeKnowledge({ id, ...payload }));
  apiMocks.deleteKnowledge.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("KnowledgePage", () => {
  it("renders entries with title, category and tags", async () => {
    renderPage();

    expect(await screen.findByText("STAR 法则")).toBeInTheDocument();
    expect(screen.getByText("简历技巧")).toBeInTheDocument();
    expect(screen.getByText("简历")).toBeInTheDocument();
    expect(screen.getByText("STAR")).toBeInTheDocument();
    expect(apiMocks.listKnowledge).toHaveBeenCalledWith({ q: "", category: "" });
  });

  it("passes the search keyword to the API", async () => {
    renderPage();
    await screen.findByText("STAR 法则");

    const searchInput = screen.getByPlaceholderText("搜索标题或正文");
    fireEvent.change(searchInput, { target: { value: "量化" } });
    fireEvent.keyDown(searchInput, { key: "Enter", code: "Enter", keyCode: 13 });

    await waitFor(() => {
      expect(apiMocks.listKnowledge).toHaveBeenLastCalledWith({ q: "量化", category: "" });
    });
  });

  it("filters entries by tag locally", async () => {
    apiMocks.listKnowledge.mockResolvedValue([
      makeKnowledge(),
      makeKnowledge({ id: 2, title: "谈薪话术", tags: ["求职策略"] }),
    ]);
    renderPage();
    await screen.findByText("STAR 法则");
    expect(screen.getByText("谈薪话术")).toBeInTheDocument();

    // 选中「简历」标签后，只保留带该标签的条目。
    const combobox = screen.getByRole("combobox", { name: "标签筛选" });
    fireEvent.mouseDown(combobox);
    const option = await screen.findByText(
      (content, element) => content === "简历" && !!element?.closest(".ant-select-item-option"),
    );
    fireEvent.click(option);

    await waitFor(() => {
      expect(screen.queryByText("谈薪话术")).not.toBeInTheDocument();
    });
    expect(screen.getByText("STAR 法则")).toBeInTheDocument();
  });

  it("creates a new entry through the form modal", async () => {
    renderPage();
    await screen.findByText("STAR 法则");

    fireEvent.click(screen.getByRole("button", { name: /新增知识/ }));
    fireEvent.change(screen.getByPlaceholderText("如：STAR 法则 / 自我介绍模板"), {
      target: { value: "自我介绍模板" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => {
      expect(apiMocks.createKnowledge).toHaveBeenCalledTimes(1);
    });
    const payload = apiMocks.createKnowledge.mock.calls[0][0];
    expect(payload.title).toBe("自我介绍模板");
    expect(payload.category).toBe("其他"); // 未改分类时使用表单默认值
  });

  it("edits an entry through the row menu", async () => {
    renderPage();
    await screen.findByText("STAR 法则");

    fireEvent.click(screen.getByRole("button", { name: "更多操作" }));
    fireEvent.click(await screen.findByText("编辑"));

    fireEvent.change(await screen.findByPlaceholderText("如：STAR 法则 / 自我介绍模板"), {
      target: { value: "STAR 法则（修订）" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => {
      expect(apiMocks.updateKnowledge).toHaveBeenCalledTimes(1);
    });
    const [id, payload] = apiMocks.updateKnowledge.mock.calls[0];
    expect(id).toBe(1);
    expect(payload.title).toBe("STAR 法则（修订）");
  });

  it("renders markdown content in the preview modal", async () => {
    renderPage();
    await screen.findByText("STAR 法则");

    fireEvent.click(screen.getByRole("button", { name: /查\s*看/ }));

    // AssistantMessageContent 把「# 核心要点」解析成 h4，而不是显示原始井号。
    expect(await screen.findByRole("heading", { name: "核心要点" })).toBeInTheDocument();
    // 正文里的加粗被解析成 <strong>。
    expect(screen.getByText("量化结果").tagName).toBe("STRONG");
  });

  it("deletes an entry after confirmation", async () => {
    renderPage();
    await screen.findByText("STAR 法则");

    fireEvent.click(screen.getByRole("button", { name: "更多操作" }));
    fireEvent.click(await screen.findByText("删除"));

    // 二次确认弹窗出现，确认后才真正调用删除。
    const confirmations = await screen.findAllByText("删除条目「STAR 法则」？");
    expect(confirmations.length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "OK" }));

    await waitFor(() => {
      expect(apiMocks.deleteKnowledge).toHaveBeenCalledWith(1);
    });
  });

  it("shows the empty state when there are no entries", async () => {
    apiMocks.listKnowledge.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText(/知识库还是空的/)).toBeInTheDocument();
  });
});
