/** 图片暂存：限额、粘贴与移除。 */

import { App as AntdApp } from "antd";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { MAX_ATTACHMENT_COUNT } from "../utils/attachments";
import { useImageStaging } from "./useImageStaging";

function wrapper({ children }: { children: ReactNode }) {
  return <AntdApp>{children}</AntdApp>;
}

function pngFile(name = "shot.png", size = 64): File {
  return new File([new Uint8Array(size)], name, { type: "image/png" });
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

describe("useImageStaging", () => {
  it("stages selected images as data URLs", async () => {
    const { result } = renderHook(() => useImageStaging(), { wrapper });

    await act(async () => {
      await result.current.addFiles([pngFile("a.png"), pngFile("b.png")]);
    });

    expect(result.current.images).toHaveLength(2);
    expect(result.current.images[0].name).toBe("a.png");
    expect(result.current.images[0].data.startsWith("data:image/png;base64,")).toBe(true);
    expect(result.current.images[0].mime_type).toBe("image/png");
  });

  it("rejects unsupported files without staging them", async () => {
    const { result } = renderHook(() => useImageStaging(), { wrapper });

    await act(async () => {
      await result.current.addFiles([
        new File(["x"], "notes.pdf", { type: "application/pdf" }),
        new File(["x"], "notes.txt", { type: "text/plain" }),
        pngFile("ok.png"),
      ]);
    });

    expect(result.current.images.map((item) => item.name)).toEqual(["ok.png"]);
  });

  it("rejects a file over the per-image limit", async () => {
    const { result } = renderHook(() => useImageStaging(), { wrapper });

    await act(async () => {
      await result.current.addFiles([pngFile("huge.png", 2 * 1024 * 1024 + 1)]);
    });

    expect(result.current.images).toHaveLength(0);
  });

  it("caps the count at the shared limit", async () => {
    const { result } = renderHook(() => useImageStaging(), { wrapper });

    await act(async () => {
      await result.current.addFiles(
        Array.from({ length: MAX_ATTACHMENT_COUNT + 2 }, (_, index) => pngFile(`${index}.png`)),
      );
    });

    expect(result.current.images).toHaveLength(MAX_ATTACHMENT_COUNT);
  });

  it("enforces the total size across calls", async () => {
    const { result } = renderHook(() => useImageStaging(), { wrapper });

    await act(async () => {
      await result.current.addFiles([pngFile("a.png", 2 * 1024 * 1024)]);
      await result.current.addFiles([pngFile("b.png", 2 * 1024 * 1024)]);
      // 再加一张 1.5 MB 会越过 5 MB 合计上限
      await result.current.addFiles([pngFile("c.png", 1_500_000)]);
    });

    expect(result.current.images.map((item) => item.name)).toEqual(["a.png", "b.png"]);
  });

  it("names a nameless pasted blob so the backend can validate it", async () => {
    const { result } = renderHook(() => useImageStaging(), { wrapper });
    const blob = new File([new Uint8Array(8)], "", { type: "image/png" });

    act(() => {
      result.current.onPaste(pasteEventWith([blob]));
    });

    await waitFor(() => expect(result.current.images).toHaveLength(1));
    expect(result.current.images[0].name).toBe("clipboard-1.png");
  });

  it("ignores a paste that contains no image", () => {
    const { result } = renderHook(() => useImageStaging(), { wrapper });

    act(() => {
      result.current.onPaste({
        clipboardData: { items: [{ kind: "string", type: "text/plain" }] },
        preventDefault: () => {
          throw new Error("不该拦截纯文本粘贴");
        },
      } as unknown as React.ClipboardEvent<HTMLElement>);
    });

    expect(result.current.images).toHaveLength(0);
  });

  it("removes and clears staged images", async () => {
    const { result } = renderHook(() => useImageStaging(), { wrapper });
    await act(async () => {
      await result.current.addFiles([pngFile("a.png"), pngFile("b.png")]);
    });

    act(() => result.current.removeImage(result.current.images[0].id));
    expect(result.current.images.map((item) => item.name)).toEqual(["b.png"]);

    act(() => result.current.clear());
    expect(result.current.images).toHaveLength(0);
  });
});
