/** 助手消息的安全 Markdown 子集、附件和来源展示。 */

import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileWordOutlined,
  PushpinFilled,
  StarFilled,
} from "@ant-design/icons";
import { Collapse, Image, Tag, Tooltip, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { AssistantAttachment, AssistantSource, AssistantToolCall } from "../../../types";
import {
  attachmentStyle,
  canPreviewImage,
  isMarkdownTableDivider,
  parseMarkdownTableRow,
  renderInlineMarkdown,
} from "../assistantUtils";

/** 文档按扩展名区分图标：pdf 和 docx 混在一串标签里时，图标比文件名更好认。 */
function attachmentIcon(name: string, kind: string) {
  if (kind !== "document") return <FileTextOutlined />;
  return name.toLowerCase().endsWith(".pdf") ? <FilePdfOutlined /> : <FileWordOutlined />;
}

export function AssistantMessageContent({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  const blocks: ReactNode[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const tableHeader = parseMarkdownTableRow(lines[index]);
    if (tableHeader && isMarkdownTableDivider(lines[index + 1] ?? "", tableHeader.length)) {
      const rows: string[][] = [];
      let nextIndex = index + 2;
      while (nextIndex < lines.length) {
        const row = parseMarkdownTableRow(lines[nextIndex]);
        if (!row || row.length !== tableHeader.length) break;
        rows.push(row);
        nextIndex += 1;
      }
      blocks.push(
        <div key={`table-${index}`} className="assistant-markdown-table-wrap" tabIndex={0}>
          <table>
            <thead>
              <tr>
                {tableHeader.map((cell, cellIndex) => (
                  <th key={`header-${cellIndex}`}>{renderInlineMarkdown(cell)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`cell-${rowIndex}-${cellIndex}`}>{renderInlineMarkdown(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      index = nextIndex - 1;
      continue;
    }

    const line = lines[index];
    const heading = line.match(/^#{1,3}\s+(.+)$/);
    const bullet = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*(\d+)[.)]\s+(.+)$/);
    if (heading) {
      blocks.push(<h4 key={`heading-${index}`}>{renderInlineMarkdown(heading[1])}</h4>);
      continue;
    }
    if (bullet || ordered) {
      blocks.push(
        <div key={`list-${index}`} className="assistant-markdown-list-item">
          <span aria-hidden="true">{ordered ? `${ordered[1]}.` : "•"}</span>
          <div>{renderInlineMarkdown(bullet?.[1] ?? ordered?.[2] ?? "")}</div>
        </div>,
      );
      continue;
    }
    if (!line.trim()) {
      blocks.push(<div key={`space-${index}`} className="assistant-markdown-spacer" />);
      continue;
    }
    blocks.push(<p key={`paragraph-${index}`}>{renderInlineMarkdown(line)}</p>);
  }

  return <div className="assistant-message-content assistant-message-content--rich">{blocks}</div>;
}

export function StreamingStatus({ message }: { message: string }) {
  return (
    <div className="assistant-streaming-status" role="status">
      <span className="assistant-streaming-dot" aria-hidden="true" />
      <span>{message}</span>
      <span className="assistant-streaming-ellipsis" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}

export function ConversationTitle({
  title,
  pinned,
  favorite,
  onSelect,
}: {
  title: string;
  pinned: boolean;
  favorite: boolean;
  onSelect: () => void;
}) {
  const titleRef = useRef<HTMLSpanElement>(null);
  const [overflowDistance, setOverflowDistance] = useState(0);

  useEffect(() => {
    const element = titleRef.current;
    if (!element) return;

    const updateOverflowDistance = () => {
      const nextDistance = Math.max(0, element.scrollWidth - element.clientWidth);
      setOverflowDistance((current) => (current === nextDistance ? current : nextDistance));
    };
    updateOverflowDistance();

    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(updateOverflowDistance);
    observer?.observe(element);
    window.addEventListener("resize", updateOverflowDistance);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateOverflowDistance);
    };
  }, [title]);

  return (
    <Tooltip title={title} placement="right">
      <button
        type="button"
        className="assistant-conversation-button"
        aria-label={title}
        onClick={onSelect}
      >
        {(pinned || favorite) && (
          <span className="assistant-conversation-flags" aria-hidden="true">
            {pinned && <PushpinFilled />}
            {favorite && <StarFilled />}
          </span>
        )}
        <span
          ref={titleRef}
          className={
            overflowDistance > 0
              ? "assistant-conversation-title is-overflowing"
              : "assistant-conversation-title"
          }
          style={attachmentStyle(overflowDistance)}
        >
          <span>{title}</span>
        </span>
      </button>
    </Tooltip>
  );
}

export function MessageAttachments({
  attachments,
}: {
  attachments: Array<
    AssistantAttachment | { name: string; kind: "text" | "image" | "document"; data: string }
  >;
}) {
  if (!attachments.length) return null;
  const notes = attachments.flatMap((attachment) =>
    "notes" in attachment ? attachment.notes : [],
  );
  return (
    <div className="assistant-message-attachments">
      {attachments.map((attachment, index) => {
        const dataUrl = "data_url" in attachment ? attachment.data_url : attachment.data;
        const mimeType = "mime_type" in attachment ? attachment.mime_type : "";
        if (attachment.kind === "image" && dataUrl && canPreviewImage(mimeType)) {
          return (
            <Image
              key={`${attachment.name}-${index}`}
              src={dataUrl}
              alt={attachment.name}
              className="assistant-message-image"
            />
          );
        }
        return (
          // 文件名是用户给的，长度没有上限；标签本身不换行，不截断就会顶出气泡。
          <Tooltip key={`${attachment.name}-${index}`} title={attachment.name}>
            <Tag
              className="assistant-attachment-tag"
              icon={attachmentIcon(attachment.name, attachment.kind)}
            >
              {attachment.name}
            </Tag>
          </Tooltip>
        );
      })}
      {notes.length > 0 && <span className="assistant-attachment-notes">{notes.join("；")}</span>}
    </div>
  );
}

/** 工具名的中文说法；没列到的直接显示原名。 */
const TOOL_LABELS: Record<string, string> = {
  get_overview: "查看整体概览",
  list_jobs: "查询岗位",
  get_job: "查看岗位详情",
  list_resumes: "查询简历",
  get_resume: "查看简历详情",
  get_profile: "查看个人资料",
  create_job: "新增岗位",
  update_job: "修改岗位",
  update_profile: "更新个人资料",
};

export function MessageToolCalls({ calls }: { calls: AssistantToolCall[] }) {
  if (!calls.length) return null;
  // 刻意不做成折叠面板：助手动了用户的数据，这件事必须一眼可见，而不是藏起来
  // 等用户点开（对比下面的参考来源，那才是可以折叠的次要信息）。
  return (
    <ul className="assistant-tool-calls">
      {calls.map((call, index) => (
        <li key={`${call.name}-${index}`}>
          {call.ok ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
          <Typography.Text strong style={{ marginLeft: 6 }}>
            {TOOL_LABELS[call.name] ?? call.name}
          </Typography.Text>
          {call.ok ? (
            <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
              {call.summary}
            </Typography.Text>
          ) : (
            <Typography.Text type="danger" style={{ marginLeft: 8 }}>
              失败：{call.error}
            </Typography.Text>
          )}
          {call.ok && call.link && (
            // 用 href 而不是 router Link：这个组件也会被单独渲染在测试里。
            <Typography.Link href={call.link} style={{ marginLeft: 8 }}>
              前往查看
            </Typography.Link>
          )}
        </li>
      ))}
    </ul>
  );
}

export function MessageSources({ sources }: { sources: AssistantSource[] }) {
  if (!sources.length) return null;
  return (
    <Collapse
      className="assistant-sources"
      size="small"
      items={[
        {
          key: "sources",
          label: `参考来源（${sources.length}）`,
          children: (
            <ol>
              {sources.map((source) => (
                <li key={source.url}>
                  <Typography.Link href={source.url} target="_blank" rel="noopener noreferrer">
                    {source.title || source.url}
                  </Typography.Link>
                  {source.snippet && (
                    <Typography.Text type="secondary">{source.snippet}</Typography.Text>
                  )}
                </li>
              ))}
            </ol>
          ),
        },
      ]}
    />
  );
}
