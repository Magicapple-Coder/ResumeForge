/** 附件类型判定与限额：助手和识别两条链路共用这一份实现。 */

import { describe, expect, it } from "vitest";
import {
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENT_COUNT,
  MAX_TOTAL_ATTACHMENT_BYTES,
  classifyAttachment,
} from "./attachments";

function fileOf(name: string, type: string, size = 8): File {
  return new File([new Uint8Array(size)], name, { type });
}

describe("classifyAttachment", () => {
  it("accepts images whose extension and MIME agree", () => {
    expect(classifyAttachment(fileOf("shot.png", "image/png"))).toEqual({
      kind: "image",
      mimeType: "image/png",
    });
    expect(classifyAttachment(fileOf("shot.JPG", "image/jpeg"))).toEqual({
      kind: "image",
      mimeType: "image/jpeg",
    });
  });

  it("rejects a file whose extension and declared type disagree", () => {
    expect(classifyAttachment(fileOf("shot.png", "image/jpeg"))).toBeNull();
    expect(classifyAttachment(fileOf("resume.exe", "text/plain"))).toBeNull();
  });

  it("rejects unsupported extensions", () => {
    expect(classifyAttachment(fileOf("notes.pdf", "application/pdf"))).toBeNull();
    expect(classifyAttachment(fileOf("archive.zip", "application/zip"))).toBeNull();
  });

  it("accepts text attachments for the assistant", () => {
    expect(classifyAttachment(fileOf("notes.md", "text/markdown"))).toEqual({
      kind: "text",
      mimeType: "text/markdown",
    });
    // 浏览器给不出类型时按扩展名兜底
    expect(classifyAttachment(fileOf("notes.txt", ""))).toEqual({
      kind: "text",
      mimeType: "text/plain",
    });
  });
});

describe("limits", () => {
  it("matches the backend contract", () => {
    // 这些值必须与 backend/app/services/attachments.py 一致
    expect(MAX_ATTACHMENT_COUNT).toBe(4);
    expect(MAX_ATTACHMENT_BYTES).toBe(2 * 1024 * 1024);
    expect(MAX_TOTAL_ATTACHMENT_BYTES).toBe(5 * 1024 * 1024);
    // base64 会把体积放大约三分之一，合计上限必须留在后端 8 MB 请求体之内
    expect((MAX_TOTAL_ATTACHMENT_BYTES * 4) / 3).toBeLessThan(8 * 1024 * 1024);
  });
});
