/** 求职助手附件校验和 Markdown 渲染所需的纯函数。 */

import { createElement } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { AssistantAttachmentInput } from "../../types";

// 附件限值、类型判定与读取和岗位/资料识别共用，实现在 utils 里；这里保留
// 原有导入路径，助手侧调用方不必跟着改。
export {
  IMAGE_MIME_BY_EXTENSION,
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENT_COUNT,
  MAX_TOTAL_ATTACHMENT_BYTES,
  classifyAttachment,
  readAsDataUrl,
  type AttachmentClassification,
} from "../../utils/attachments";

export interface PendingAttachment extends AssistantAttachmentInput {
  id: number;
  size: number;
  kind: "text" | "image";
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

export function attachmentStyle(distance: number): CSSProperties {
  return { "--assistant-title-scroll-distance": `-${distance}px` } as CSSProperties;
}
