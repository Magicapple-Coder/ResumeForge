/**
 * 模板一览：缩略图必须反映用户当前设定的版式与字号系数。
 *
 * 这是"选模板即见预览"里最容易悄悄坏掉的一环——缩略图少传 `format_config` 不会报错，
 * 只会让用户按一张"没带字号系数"的图选模板，选完才发现不一样。所以这里钉住请求参数：
 * `format_name`（基础版式）与 `format_config`（含 `font_scale_adjust`）都要带上。
 */
import { App as AntdApp } from "antd";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TEMPLATE_CATALOG } from "../../test/resumeFixtures";
import type { ResumeLayout } from "../../types";
import TemplateGalleryModal from "./TemplateGalleryModal";

const apiMocks = vi.hoisted(() => ({
  fetchResumeTemplates: vi.fn(),
  previewResumeTemplate: vi.fn(),
}));

// 展开真实模块再覆盖：生产代码新增导出时不会因为这里只列了两个而直接抛错。
vi.mock("../../api/resumes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/resumes")>()),
  fetchResumeTemplates: apiMocks.fetchResumeTemplates,
  previewResumeTemplate: apiMocks.previewResumeTemplate,
}));

const LAYOUT_WITH_ADJUST: ResumeLayout = {
  template: "classic",
  format_name: "compact",
  page_limit: 1,
  font_scale: "standard",
  format_config: { font_scale_adjust: 1.021, accent: "#123456" },
};

beforeEach(() => {
  apiMocks.fetchResumeTemplates.mockReset();
  apiMocks.previewResumeTemplate.mockReset();
  apiMocks.fetchResumeTemplates.mockResolvedValue(TEMPLATE_CATALOG);
  apiMocks.previewResumeTemplate.mockResolvedValue("<html><body>简历</body></html>");
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function renderModal(layout: ResumeLayout) {
  render(
    <AntdApp>
      <TemplateGalleryModal open layout={layout} onSelect={() => {}} onClose={() => {}} />
    </AntdApp>,
  );
}

describe("TemplateGalleryModal · 缩略图反映字号系数（洞2）", () => {
  it("预览请求带上 format_name 与当前 format_config（含字号系数）", async () => {
    renderModal(LAYOUT_WITH_ADJUST);

    await waitFor(() =>
      expect(apiMocks.previewResumeTemplate).toHaveBeenCalledTimes(
        TEMPLATE_CATALOG.templates.length,
      ),
    );
    // 关键：format_config 必须原样透出——后端靠它把用户拖出来的字号系数乘进档位基准，
    // 少了它缩略图就会停在"无系数"的默认字号。
    expect(apiMocks.previewResumeTemplate).toHaveBeenCalledWith(
      expect.objectContaining({
        template_name: "modern",
        format_name: "compact",
        format_config: { font_scale_adjust: 1.021, accent: "#123456" },
        font_scale: "standard",
      }),
    );
  });

  it("没有 format_config 时按空对象下发，不伪造系数", async () => {
    const layoutWithoutConfig: ResumeLayout = {
      template: "classic",
      format_name: "compact",
      page_limit: 1,
      font_scale: "standard",
    };
    renderModal(layoutWithoutConfig);

    await waitFor(() => expect(apiMocks.previewResumeTemplate).toHaveBeenCalled());
    const firstCall = apiMocks.previewResumeTemplate.mock.calls[0][0];
    expect(firstCall.format_name).toBe("compact");
    // 没有系数就不该凭空造一个：后端会把空覆盖与 format_name 正常叠加。
    expect(firstCall.format_config ?? {}).toEqual({});
  });
});
