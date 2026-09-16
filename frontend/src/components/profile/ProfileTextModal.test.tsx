/** 个人资料识别弹窗：截图与文档暂存、识别原文与警告的展示。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProfileTextModal from "./ProfileTextModal";

const IMAGE = {
  id: 1,
  name: "截图.png",
  mime_type: "image/png",
  kind: "image" as const,
  data: "data:image/png;base64,iVBORw0KGgo=",
  size: 128,
};

const DOCX = {
  id: 2,
  name: "简历.docx",
  mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  kind: "document" as const,
  data: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,eA==",
  size: 256,
};

function renderModal(overrides: Partial<React.ComponentProps<typeof ProfileTextModal>> = {}) {
  const props = {
    open: true,
    text: "",
    warnings: [] as string[],
    parsing: false,
    recognizedText: "",
    recognitionSource: null,
    files: [] as (typeof IMAGE | typeof DOCX)[],
    filesReading: false,
    onTextChange: vi.fn(),
    onAddFiles: vi.fn(),
    onRemoveFile: vi.fn(),
    onPasteFiles: vi.fn(),
    onClose: vi.fn(),
    onParse: vi.fn(),
    ...overrides,
  };
  render(
    <AntdApp>
      <ProfileTextModal {...props} />
    </AntdApp>,
  );
  return props;
}

afterEach(() => cleanup());

describe("ProfileTextModal", () => {
  it("renders staged screenshots and reports removal", () => {
    const props = renderModal({ files: [IMAGE] });

    expect(screen.getByAltText("截图.png")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "移除文件 截图.png" }));

    expect(props.onRemoveFile).toHaveBeenCalledWith(IMAGE.id);
  });

  it("renders documents as file tags rather than trying to preview them", () => {
    renderModal({ files: [DOCX] });

    expect(screen.getByText("简历.docx")).toBeInTheDocument();
    expect(screen.queryByAltText("简历.docx")).not.toBeInTheDocument();
  });

  it("forwards pasted images from the textarea", () => {
    const props = renderModal();

    fireEvent.paste(screen.getByLabelText("个人资料文本"), { clipboardData: { items: [] } });

    expect(props.onPasteFiles).toHaveBeenCalledOnce();
  });

  it("forwards files chosen from the picker", () => {
    const onAddFiles = vi.fn();
    renderModal({ onAddFiles });
    const input = document.querySelector(
      'input[type="file"][aria-label="添加截图或文档"]',
    ) as HTMLInputElement;
    const file = new File([new Uint8Array(8)], "picker.png", { type: "image/png" });

    fireEvent.change(input, { target: { files: [file] } });

    expect(onAddFiles).toHaveBeenCalledOnce();
    expect((onAddFiles.mock.calls[0][0] as File[])[0].name).toBe("picker.png");
  });

  it("shows warnings and the text the model read", async () => {
    renderModal({
      warnings: ["图片识别失败，可能是当前模型不支持图片输入（需要多模态模型）。"],
      recognizedText: "张三\n13800000000",
    });

    // 用警告自身的措辞，别用"多模态"——弹窗说明里也有这四个字
    expect(screen.getByText(/图片识别失败/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("查看模型识别到的原文（请对照截图核对）"));

    await waitFor(() => expect(screen.getByText(/13800000000/)).toBeInTheDocument());
  });

  it("renders no recognition block when there is nothing to show", () => {
    renderModal();

    expect(screen.queryByText("查看模型识别到的原文（请对照截图核对）")).not.toBeInTheDocument();
    expect(screen.queryByText("AI 识别")).not.toBeInTheDocument();
    expect(screen.queryByText("本地规则")).not.toBeInTheDocument();
  });

  it("keeps saying whether AI or local rules produced the fields", async () => {
    renderModal({ recognitionSource: "local", recognizedText: "" });

    // 本地规则的结果只有来源标记、没有抄录原文，这时标记更不能省。
    const badge = screen.getByText("本地规则");
    fireEvent.mouseEnter(badge);

    expect(await screen.findByRole("tooltip")).toHaveTextContent("请重点核对");
  });
});
