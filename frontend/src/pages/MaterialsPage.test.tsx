/**
 * 资料箱：卡片点击查看详情。
 *
 * 卡片里只有正文摘要与附件数量，真正的内容（正文全文、备注、附件清单）在详情里，
 * 所以"点得开"这件事必须有测试守着——它是这一页唯一的阅读入口。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Material } from "../types";
import MaterialsPage from "./MaterialsPage";

const apiMocks = vi.hoisted(() => ({
  listMaterials: vi.fn(),
  listMaterialCategories: vi.fn(),
  createMaterial: vi.fn(),
  updateMaterial: vi.fn(),
  deleteMaterial: vi.fn(),
}));

vi.mock("../api/material", () => apiMocks);

const ITEMS: Material[] = [
  {
    id: 1,
    title: "护士执业资格证",
    category: "证书",
    content: "2024 年通过考试，证书编号示例。",
    url: "",
    files: [],
    note: "入职时要带原件",
    created_at: "2026-09-01T08:00:00",
    updated_at: "2026-09-10T09:30:00",
  },
];

function renderPage() {
  return render(
    <AntdApp>
      <MaterialsPage />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.listMaterials.mockReset().mockResolvedValue(ITEMS);
  apiMocks.listMaterialCategories.mockReset().mockResolvedValue(["证书"]);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("MaterialsPage", () => {
  it("渲染资料卡片", async () => {
    renderPage();

    expect(await screen.findByText("护士执业资格证")).toBeInTheDocument();
    expect(screen.getByText("证书")).toBeInTheDocument();
  });

  it("点卡片打开详情，看得到正文与备注", async () => {
    renderPage();
    await screen.findByText("护士执业资格证");

    fireEvent.click(screen.getByRole("button", { name: /打开资料「护士执业资格证」的详情/ }));

    expect(await screen.findByText("正文")).toBeInTheDocument();
    expect(screen.getByText("备注")).toBeInTheDocument();
    expect(screen.getByText("入职时要带原件")).toBeInTheDocument();
    expect(screen.getAllByText(/2024 年通过考试/).length).toBeGreaterThan(0);
  });
});
