/** 求职助手附件校验和 Markdown 渲染所需的纯函数。 */

import { createElement } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { AssistantAttachmentInput } from "../../types";

export const MAX_ATTACHMENT_COUNT = 4;
export const MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024;
export const MAX_TOTAL_ATTACHMENT_BYTES = 5 * 1024 * 1024;

export const IMAGE_MIME_BY_EXTENSION: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
  gif: "image/gif",
};
const TEXT_MIMES_BY_EXTENSION: Record<string, ReadonlySet<string>> = {
  txt: new Set(["text/plain"]),
  md: new Set(["text/markdown", "text/plain"]),
  json: new Set(["application/json", "text/json", "text/plain"]),
  csv: new Set(["text/csv", "application/csv", "text/plain"]),
};
const TEXT_CANONICAL_MIME_BY_EXTENSION: Record<string, string> = {
  txt: "text/plain",
  md: "text/markdown",
  json: "application/json",
  csv: "text/csv",
};

export interface PendingAttachment extends AssistantAttachmentInput {
  id: number;
  size: number;
  kind: "text" | "image";
}

interface AttachmentClassification {
  kind: "text" | "image";
  mimeType: string;
}

export function safeExternalUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export function renderInlineMarkdown(value: string): ReactNode[] {
  const tokenPattern =
    /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<，。！？、）】〉》]+))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(value)) !== null) {
    if (match.index > cursor) nodes.push(value.slice(cursor, match.index));
    if (match[2]) {
      nodes.push(createElement("strong", { key: `strong-${match.index}` }, match[2]));
    } else if (match[3]) {
      nodes.push(createElement("code", { key: `code-${match.index}` }, match[3]));
    } else {
      const url = safeExternalUrl(match[5] ?? match[6]);
      nodes.push(
        url
          ? createElement(
              "a",
              {
                key: `link-${match.index}`,
                href: url,
                target: "_blank",
                rel: "noopener noreferrer",
              },
              match[4] ?? match[6],
            )
          : (match[4] ?? match[6]),
      );
    }
    cursor = tokenPattern.lastIndex;
  }
  if (cursor < value.length) nodes.push(value.slice(cursor));
  return nodes;
}

export function parseMarkdownTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return null;
  const source = trimmed.startsWith("|") ? trimmed.slice(1) : trimmed;
  const row = (source.endsWith("|") ? source.slice(0, -1) : source)
    .split("|")
    .map((cell) => cell.trim());
  return row.length >= 2 && row.every(Boolean) ? row : null;
}

export function isMarkdownTableDivider(line: string, columnCount: number): boolean {
  const cells = parseMarkdownTableRow(line);
  return cells?.length === columnCount && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

export function positiveId(value: string | null): number | undefined {
  return value && /^\d+$/.test(value) && Number(value) > 0 ? Number(value) : undefined;
}

function fileExtension(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

export function classifyAttachment(file: File): AttachmentClassification | null {
  const extension = fileExtension(file.name);
  const declaredMime = file.type.split(";", 1)[0].trim().toLowerCase();
  const imageMime = IMAGE_MIME_BY_EXTENSION[extension];
  if (imageMime) {
    return declaredMime === imageMime ? { kind: "image", mimeType: imageMime } : null;
  }

  const textMimes = TEXT_MIMES_BY_EXTENSION[extension];
  if (textMimes && (!declaredMime || textMimes.has(declaredMime))) {
    return {
      kind: "text",
      mimeType: declaredMime || TEXT_CANONICAL_MIME_BY_EXTENSION[extension],
    };
  }
  return null;
}

export function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("读取附件失败"));
    reader.readAsDataURL(file);
  });
}

export function attachmentStyle(distance: number): CSSProperties {
  return { "--assistant-title-scroll-distance": `-${distance}px` } as CSSProperties;
}
