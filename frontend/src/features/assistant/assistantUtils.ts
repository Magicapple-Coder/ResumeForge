/** 求职助手附件校验和 Markdown 渲染所需的纯函数。 */

import { createElement } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { AssistantAttachmentInput, AssistantSourceNumber } from "../../types";

// 附件限值、类型判定与读取和岗位/资料识别共用，实现在 utils 里；这里保留
// 原有导入路径，助手侧调用方不必跟着改。
export {
  ASSISTANT_ACCEPT,
  DOCUMENT_MIME_BY_EXTENSION,
  IMAGE_MIME_BY_EXTENSION,
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENT_COUNT,
  MAX_TOTAL_ATTACHMENT_BYTES,
  canPreviewImage,
  classifyAttachment,
  readAsDataUrl,
  type AttachmentClassification,
} from "../../utils/attachments";

export interface PendingAttachment extends AssistantAttachmentInput {
  id: number;
  size: number;
  /** document：pdf/docx，正文由后端在本机提取后再进模型。 */
  kind: "text" | "image" | "document";
}

/** 页头放不下太多技能名字，超过这个数量就收成"等 N 个"。 */
const MAX_LISTED_SKILL_NAMES = 2;

export function summarizeSkillNames(skills: { name: string }[]): string {
  const names = skills.map((skill) => skill.name);
  if (names.length <= MAX_LISTED_SKILL_NAMES) return names.join("、");
  return `${names.slice(0, MAX_LISTED_SKILL_NAMES).join("、")} 等 ${names.length} 个`;
}

export function safeExternalUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/**
 * 按「编号 → url」映射解析 [来源N] 的链接地址。
 *
 * 解析不到（映射缺失、编号越界、URL 不是 http/https）一律返回 null，让调用方退化成
 * 纯文本——"一个能点却跳错地方的链接，比没有链接更糟"，宁可不可点也不跳错。
 */
export function resolveSourceUrl(
  sourceMap: AssistantSourceNumber[] | undefined,
  number: number,
): string | null {
  if (!sourceMap) return null;
  const entry = sourceMap.find((item) => item.number === number);
  return entry ? safeExternalUrl(entry.url) : null;
}

export function renderInlineMarkdown(
  value: string,
  sourceMap?: AssistantSourceNumber[],
): ReactNode[] {
  const tokenPattern =
    /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\[来源(\d+)\]|(https?:\/\/[^\s<，。！？、）】〉》]+))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(value)) !== null) {
    if (match.index > cursor) nodes.push(value.slice(cursor, match.index));
    if (match[2]) {
      nodes.push(createElement("strong", { key: `strong-${match.index}` }, match[2]));
    } else if (match[3]) {
      nodes.push(createElement("code", { key: `code-${match.index}` }, match[3]));
    } else if (match[6]) {
      // [来源N]：按持久化的编号映射解析，编号对不上就保持纯文本。
      const url = resolveSourceUrl(sourceMap, Number(match[6]));
      nodes.push(
        url
          ? createElement(
              "a",
              {
                key: `source-${match.index}`,
                href: url,
                target: "_blank",
                rel: "noopener noreferrer",
              },
              match[0],
            )
          : match[0],
      );
    } else {
      const url = safeExternalUrl(match[5] ?? match[7]);
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
              match[4] ?? match[7],
            )
          : (match[4] ?? match[7]),
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

export function attachmentStyle(distance: number): CSSProperties {
  return { "--assistant-title-scroll-distance": `-${distance}px` } as CSSProperties;
}
