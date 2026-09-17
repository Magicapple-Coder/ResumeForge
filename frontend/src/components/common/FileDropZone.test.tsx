/**
 * 拖拽导入容器。
 *
 * 这一层此前完全没有测试，而项目里六个导入入口（岗位识别、备选岗位截图、资料箱附件、
 * 个人照片、助手附件、经历参考文件/技能包/模板/数据集）全都挂在它上面——它要是坏了，
 * "拖进来"这件事会在所有地方一起失灵，却没有任何一条断言会红。
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FileDropZone from "./FileDropZone";

function file(name: string, type = ""): File {
  return new File(["内容"], name, { type });
}

/** 模拟一次拖拽：`types` 里没有 "Files" 时浏览器会走自己的默认行为。 */
function dropOn(element: HTMLElement, files: File[], types: string[] = ["Files"]) {
  fireEvent.drop(element, { dataTransfer: { files, types } });
}

afterEach(cleanup);

describe("FileDropZone", () => {
  it("hands the dropped file to the caller", () => {
    const onFiles = vi.fn();
    render(
      <FileDropZone onFiles={onFiles}>
        <button type="button">导入</button>
      </FileDropZone>,
    );

    const target = screen.getByRole("button", { name: "导入" }).parentElement as HTMLElement;
    const dropped = file("总结.md");
    dropOn(target, [dropped]);

    expect(onFiles).toHaveBeenCalledWith([dropped]);
  });

  it("ignores a drag that carries no files", () => {
    const onFiles = vi.fn();
    render(
      <FileDropZone onFiles={onFiles}>
        <div data-testid="zone">拖这里</div>
      </FileDropZone>,
    );

    // 拖一段文字或一个链接进来时不该抢走浏览器的默认行为——资料页还有区块拖动排序。
    dropOn(screen.getByTestId("zone"), [], ["text/plain"]);

    expect(onFiles).not.toHaveBeenCalled();
  });

  it("filters by accept and reports what it dropped", () => {
    const onFiles = vi.fn();
    const onRejected = vi.fn();
    render(
      <FileDropZone accept=".md,.txt" onFiles={onFiles} onRejected={onRejected}>
        <div data-testid="zone">拖这里</div>
      </FileDropZone>,
    );

    const good = file("总结.md");
    const bad = file("照片.png", "image/png");
    dropOn(screen.getByTestId("zone"), [good, bad]);

    expect(onFiles).toHaveBeenCalledWith([good]);
    expect(onRejected).toHaveBeenCalledWith(1);
  });

  it("does not call the caller at all when everything was rejected", () => {
    const onFiles = vi.fn();
    const onRejected = vi.fn();
    render(
      <FileDropZone accept=".md" onFiles={onFiles} onRejected={onRejected}>
        <div data-testid="zone">拖这里</div>
      </FileDropZone>,
    );

    dropOn(screen.getByTestId("zone"), [file("简历.pdf", "application/pdf")]);

    expect(onFiles).not.toHaveBeenCalled();
    expect(onRejected).toHaveBeenCalledWith(1);
  });

  it("keeps only the first file when multiple is false", () => {
    const onFiles = vi.fn();
    render(
      <FileDropZone multiple={false} onFiles={onFiles}>
        <div data-testid="zone">拖这里</div>
      </FileDropZone>,
    );

    const first = file("a.md");
    dropOn(screen.getByTestId("zone"), [first, file("b.md")]);

    expect(onFiles).toHaveBeenCalledWith([first]);
  });

  it("does nothing while disabled", () => {
    const onFiles = vi.fn();
    render(
      <FileDropZone disabled onFiles={onFiles}>
        <div data-testid="zone">拖这里</div>
      </FileDropZone>,
    );

    dropOn(screen.getByTestId("zone"), [file("总结.md")]);

    expect(onFiles).not.toHaveBeenCalled();
  });

  it("shows the hint overlay while a file is over it, and hides it after the drop", () => {
    render(
      <FileDropZone hint="松开即可导入" onFiles={vi.fn()}>
        <div data-testid="zone">拖这里</div>
      </FileDropZone>,
    );

    const zone = screen.getByTestId("zone").parentElement as HTMLElement;
    expect(screen.queryByText("松开即可导入")).not.toBeInTheDocument();

    fireEvent.dragEnter(zone, { dataTransfer: { files: [], types: ["Files"] } });
    expect(screen.getByText("松开即可导入")).toBeInTheDocument();

    // 拖进子元素时浏览器会连续补发 dragenter/dragleave，用深度计数判稳；
    // 所以留在原地不该把覆盖层闪掉。
    fireEvent.dragLeave(zone, { dataTransfer: { files: [], types: ["Files"] } });
    fireEvent.drop(zone, { dataTransfer: { files: [file("a.md")], types: ["Files"] } });

    expect(screen.queryByText("松开即可导入")).not.toBeInTheDocument();
  });
});
