/** 模板市场：展示四套场景预设、按预设预览、使用模板。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TemplateMarketTab from "./TemplateMarketTab";

const apiMocks = vi.hoisted(() => ({
  fetchResumeTemplates: vi.fn(),
  previewResumeTemplate: vi.fn(),
}));

vi.mock("../../api/resumes", () => apiMocks);

const CATALOG = {
  templates: [
    { name: "modern", label: "现代", description: "" },
    { name: "classic", label: "经典", description: "" },
    { name: "elegant", label: "优雅", description: "" },
    { name: "compact", label: "精简", description: "" },
  ],
  format_presets: [
    { name: "compact", label: "紧凑", description: "", config: {} },
    { name: "spacious", label: "舒展", description: "", config: {} },
  ],
  font_scales: [
    { name: "small", label: "小字号", description: "", base_px: 12 },
    { name: "standard", label: "标准字号", description: "", base_px: 14 },
  ],
  format_fields: [],
  defaults: { template: "classic", font_scale: "standard", page_limit: 1 },
  pdf_direct_available: true,
  market: [
    {
      name: "internet",
      label: "互联网",
      category: "互联网",
      description: "适合研发投递",
      template: "modern",
      format_name: "compact",
      format_config: {},
      font_scale: "standard",
      page_limit: 1,
    },
    {
      name: "soe",
      label: "国企",
      category: "国企",
      description: "适合国企投递",
      template: "classic",
      format_name: "spacious",
      format_config: {},
      font_scale: "standard",
      page_limit: 1,
    },
    {
      name: "foreign",
      label: "外企",
      category: "外企",
      description: "适合外企投递",
      template: "elegant",
      format_name: "spacious",
      format_config: {},
      font_scale: "standard",
      page_limit: 1,
    },
    {
      name: "campus",
      label: "应届生",
      category: "应届生",
      description: "适合校招海投",
      template: "compact",
      format_name: "compact",
      format_config: {},
      font_scale: "small",
      page_limit: 1,
    },
  ],
};

function renderTab() {
  return render(
    <AntdApp>
      <TemplateMarketTab />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.fetchResumeTemplates.mockReset().mockResolvedValue(CATALOG);
  apiMocks.previewResumeTemplate.mockReset().mockResolvedValue("<html><body>预览</body></html>");
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("TemplateMarketTab", () => {
  it("展示四套场景预设与组合标签", async () => {
    renderTab();

    expect(await screen.findByText("互联网")).toBeInTheDocument();
    expect(screen.getByText("国企")).toBeInTheDocument();
    expect(screen.getByText("外企")).toBeInTheDocument();
    expect(screen.getByText("应届生")).toBeInTheDocument();
    // 每套都带「使用此模板」按钮。
    expect(screen.getAllByRole("button", { name: "使用此模板" })).toHaveLength(4);
  });

  it("点预览用预设参数渲染并打开预览弹窗", async () => {
    renderTab();
    await screen.findByText("互联网");

    fireEvent.click(screen.getAllByRole("button", { name: /预\s*览/ })[0]);

    await waitFor(() =>
      expect(apiMocks.previewResumeTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          template_name: "modern",
          format_name: "compact",
          font_scale: "standard",
          page_limit: 1,
        }),
      ),
    );
    expect(await screen.findByText("模板市场 · 互联网")).toBeInTheDocument();
  });

  it("点使用此模板提示推荐组合", async () => {
    renderTab();
    await screen.findByText("互联网");

    fireEvent.click(screen.getAllByRole("button", { name: "使用此模板" })[0]);

    expect(
      await screen.findByText(/已选用「互联网」模板组合：现代 样式 \+ 紧凑 版式 \+ 标准字号 字号/),
    ).toBeInTheDocument();
  });
});
