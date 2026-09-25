/** 「导入目标模板」弹窗：选文件 → 提交一次 multipart → 成功后刷新列表。 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntdApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TemplateImportModal from "./TemplateImportModal";

const apiMocks = vi.hoisted(() => ({ importTemplateFromFile: vi.fn() }));

vi.mock("../../api/resumeTemplates", () => ({
  importTemplateFromFile: apiMocks.importTemplateFromFile,
}));

function renderModal(overrides: Partial<{ open: boolean }> = {}) {
  const onClose = vi.fn();
  const onImported = vi.fn();
  const view = render(
    <AntdApp>
      <TemplateImportModal
        open={overrides.open ?? true}
        onClose={onClose}
        onImported={onImported}
      />
    </AntdApp>,
  );
  return { ...view, onClose, onImported };
}

/** 造一个能塞进 Upload 的 File。 */
function pngFile(name = "目标模板.png"): File {
  return new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], name, { type: "image/png" });
}

beforeEach(() => {
  apiMocks.importTemplateFromFile.mockReset();
});

afterEach(() => {
  // 不 cleanup 的话，上一个用例的弹窗还挂在 DOM 里，下一个用例就会"找到多个同名按钮"。
  cleanup();
  vi.clearAllMocks();
});

describe("TemplateImportModal", () => {
  it("没选文件时不能提交（按钮禁用）", () => {
    renderModal();
    expect(screen.getByRole("button", { name: /开始识别/ })).toBeDisabled();
  });

  it("提交后把文件与名称交给接口，成功后关闭并通知父组件刷新", async () => {
    apiMocks.importTemplateFromFile.mockResolvedValue({
      id: 9,
      name: "导入的版式",
      kind: "format",
    });
    const { onClose, onImported } = renderModal();

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });
    fireEvent.change(screen.getByRole("textbox", { name: "模板名称" }), {
      target: { value: "深蓝简洁" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始识别/ }));

    await waitFor(() => expect(apiMocks.importTemplateFromFile).toHaveBeenCalledTimes(1));
    const [file, name] = apiMocks.importTemplateFromFile.mock.calls[0];
    expect((file as File).name).toBe("目标模板.png");
    expect(name).toBe("深蓝简洁");

    await waitFor(() =>
      expect(onImported).toHaveBeenCalledWith(expect.objectContaining({ id: 9 })),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("名称留空也能提交（由模型起名）", async () => {
    apiMocks.importTemplateFromFile.mockResolvedValue({ id: 10, name: "模型起的名字" });
    renderModal();

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });
    fireEvent.click(screen.getByRole("button", { name: /开始识别/ }));

    await waitFor(() => expect(apiMocks.importTemplateFromFile).toHaveBeenCalled());
    expect(apiMocks.importTemplateFromFile.mock.calls[0][1]).toBe("");
  });

  it("接口报错时留在弹窗里，把后端的中文原因显示出来", async () => {
    apiMocks.importTemplateFromFile.mockRejectedValue(
      new Error("没能从这份文件里读出可用的版式参数"),
    );
    const { onClose } = renderModal();

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });
    fireEvent.click(screen.getByRole("button", { name: /开始识别/ }));

    expect(await screen.findByText("没能从这份文件里读出可用的版式参数")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
