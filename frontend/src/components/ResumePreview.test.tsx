import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResumePreview from "./ResumePreview";

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function getPreviewFrame(): HTMLIFrameElement {
  return screen.getByTitle("简历预览") as HTMLIFrameElement;
}

describe("ResumePreview", () => {
  it("returns the structured field path when a preview value is clicked in edit mode", () => {
    const onEditTarget = vi.fn();
    render(
      <ResumePreview
        html="<!doctype html><html><body></body></html>"
        warnings={[]}
        onEditTarget={onEditTarget}
      />,
    );

    const iframe = getPreviewFrame();
    if (!iframe.contentDocument) throw new Error("测试环境未创建 iframe document");
    iframe.contentDocument.body.innerHTML =
      '<span data-resume-path="projects.0.description.1">项目要点</span>';

    fireEvent.click(screen.getByText("编辑"));
    fireEvent.load(iframe);
    const target = iframe.contentDocument.querySelector("[data-resume-path]");
    if (!target) throw new Error("可编辑字段未渲染");
    fireEvent.click(target);

    expect(onEditTarget).toHaveBeenCalledWith("projects.0.description.1");
  });

  it("exposes editable fields as keyboard controls", () => {
    const onEditTarget = vi.fn();
    render(
      <ResumePreview
        html="<!doctype html><html><body></body></html>"
        warnings={[]}
        onEditTarget={onEditTarget}
      />,
    );
    const iframe = getPreviewFrame();
    if (!iframe.contentDocument) throw new Error("测试环境未创建 iframe document");
    iframe.contentDocument.body.innerHTML = '<span data-resume-path="summary">个人总结</span>';

    fireEvent.click(screen.getByText("编辑"));
    fireEvent.load(iframe);
    const target = iframe.contentDocument.querySelector<HTMLElement>("[data-resume-path]");
    if (!target) throw new Error("可编辑字段未渲染");

    expect(target).toHaveAttribute("role", "button");
    expect(target).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(target, { key: "Enter" });
    fireEvent.keyDown(target, { key: " " });

    expect(onEditTarget).toHaveBeenNthCalledWith(1, "summary");
    expect(onEditTarget).toHaveBeenNthCalledWith(2, "summary");
  });

  it("restores template attributes and removes edit listeners in pan mode", () => {
    const onEditTarget = vi.fn();
    render(
      <ResumePreview
        html="<!doctype html><html><body></body></html>"
        warnings={[]}
        onEditTarget={onEditTarget}
      />,
    );
    const iframe = getPreviewFrame();
    if (!iframe.contentDocument) throw new Error("测试环境未创建 iframe document");
    iframe.contentDocument.body.innerHTML =
      '<span role="note" tabindex="-1" data-resume-path="name">姓名</span>';

    fireEvent.click(screen.getByText("编辑"));
    fireEvent.load(iframe);
    const target = iframe.contentDocument.querySelector<HTMLElement>("[data-resume-path]");
    if (!target) throw new Error("可编辑字段未渲染");
    expect(target).toHaveAttribute("role", "button");

    fireEvent.click(screen.getByText("抓手"));
    expect(target).toHaveAttribute("role", "note");
    expect(target).toHaveAttribute("tabindex", "-1");
    fireEvent.click(target);

    expect(onEditTarget).not.toHaveBeenCalled();
  });
});
