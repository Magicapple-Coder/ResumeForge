/** 识别文件暂存：截图与文档的限额、粘贴、类型与移除。 */

import { App as AntdApp } from "antd";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { MAX_ATTACHMENT_COUNT } from "../utils/attachments";
import { attachmentInputs, useRecognitionFiles } from "./useRecognitionFiles";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function wrapper({ children }: { children: ReactNode }) {
  return <AntdApp>{children}</AntdApp>;
}

function pngFile(name = "shot.png", size = 64): File {
  return new File([new Uint8Array(size)], name, { type: "image/png" });
}

function documentFile(name = "resume.docx", size = 64, type = DOCX_MIME): File {
  return new File([new Uint8Array(size)], name, { type });
}

/** jsdom 的 ClipboardEvent 不允许设置 clipboardData，直接构造一个够用的替身。 */
function pasteEventWith(files: File[]): React.ClipboardEvent<HTMLElement> {
  const items = files.map((file) => ({
    kind: "file",
    type: file.type,
    getAsFile: () => file,
  }));
  return {
    clipboardData: { items },
    preventDefault: () => {},
  } as unknown as React.ClipboardEvent<HTMLElement>;
}

afterEach(() => cleanup());

describe("useRecognitionFiles", () => {
  it("stages selected images as data URLs", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });

    await act(async () => {
      await result.current.addFiles([pngFile("a.png"), pngFile("b.png")]);
    });

    expect(result.current.files).toHaveLength(2);
    expect(result.current.files[0].name).toBe("a.png");
    expect(result.current.files[0].kind).toBe("image");
    expect(result.current.files[0].data.startsWith("data:image/png;base64,")).toBe(true);
    expect(result.current.files[0].mime_type).toBe("image/png");
  });

  it("stages documents too, keeping the original bytes as a data URL", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });

    await act(async () => {
      await result.current.addFiles([documentFile("jd.docx")]);
    });

    expect(result.current.files).toHaveLength(1);
    expect(result.current.files[0].kind).toBe("document");
    expect(result.current.files[0].mime_type).toBe(DOCX_MIME);
    expect(result.current.files[0].data.startsWith(`data:${DOCX_MIME};base64,`)).toBe(true);
  });

  it("rejects text files and unknown formats without staging them", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });

    await act(async () => {
      await result.current.addFiles([
        new File(["x"], "notes.txt", { type: "text/plain" }),
        new File(["x"], "photo.heic", { type: "image/heic" }),
        pngFile("ok.png"),
      ]);
    });

    // 识别弹窗只收截图与文档：文本请直接粘进输入框。
    expect(result.current.files.map((item) => item.name)).toEqual(["ok.png"]);
  });

  it("rejects a file over the per-file limit", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });

    await act(async () => {
      await result.current.addFiles([pngFile("huge.png", 2 * 1024 * 1024 + 1)]);
    });

    expect(result.current.files).toHaveLength(0);
  });

  it("caps the count at the shared limit", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });

    await act(async () => {
      await result.current.addFiles(
        Array.from({ length: MAX_ATTACHMENT_COUNT + 2 }, (_, index) => pngFile(`${index}.png`)),
      );
    });

    expect(result.current.files).toHaveLength(MAX_ATTACHMENT_COUNT);
  });

  it("enforces the total size across calls", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });

    await act(async () => {
      await result.current.addFiles([pngFile("a.png", 2 * 1024 * 1024)]);
      await result.current.addFiles([pngFile("b.png", 2 * 1024 * 1024)]);
      // 再加一张 1.5 MB 会越过 5 MB 合计上限
      await result.current.addFiles([pngFile("c.png", 1_500_000)]);
    });

    expect(result.current.files.map((item) => item.name)).toEqual(["a.png", "b.png"]);
  });

  it("names a nameless pasted blob so the backend can validate it", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });
    const blob = new File([new Uint8Array(8)], "", { type: "image/png" });

    act(() => {
      result.current.onPaste(pasteEventWith([blob]));
    });

    await waitFor(() => expect(result.current.files).toHaveLength(1));
    expect(result.current.files[0].name).toBe("clipboard-1.png");
  });

  it("ignores a paste that contains no image", () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });

    act(() => {
      result.current.onPaste({
        clipboardData: { items: [{ kind: "string", type: "text/plain" }] },
        preventDefault: () => {
          throw new Error("不该拦截纯文本粘贴");
        },
      } as unknown as React.ClipboardEvent<HTMLElement>);
    });

    expect(result.current.files).toHaveLength(0);
  });

  it("removes and clears staged files", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });
    await act(async () => {
      await result.current.addFiles([pngFile("a.png"), pngFile("b.png")]);
    });

    act(() => result.current.removeFile(result.current.files[0].id));
    expect(result.current.files.map((item) => item.name)).toEqual(["b.png"]);

    act(() => result.current.clear());
    expect(result.current.files).toHaveLength(0);
  });
});

describe("attachmentInputs", () => {
  it("splits staged files into the two request fields", async () => {
    const { result } = renderHook(() => useRecognitionFiles(), { wrapper });
    await act(async () => {
      await result.current.addFiles([
        pngFile("shot.png"),
        documentFile("resume.docx"),
        documentFile("jd.pdf", 32, "application/pdf"),
      ]);
    });

    // pdf 的 MIME 由扩展名判定，与浏览器给的类型无关
    expect(attachmentInputs(result.current.files, "image").map((item) => item.name)).toEqual([
      "shot.png",
    ]);
    expect(attachmentInputs(result.current.files, "document").map((item) => item.name)).toEqual([
      "resume.docx",
      "jd.pdf",
    ]);
  });
});
