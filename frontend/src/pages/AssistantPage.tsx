/** AI 求职助手：流式对话、历史记录、附件与项目上下文联动。 */
import {
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  PushpinFilled,
  PushpinOutlined,
  MoreOutlined,
  PaperClipOutlined,
  PlusOutlined,
  SaveOutlined,
  SendOutlined,
  StarFilled,
  StarOutlined,
  StopOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Collapse,
  Empty,
  Image,
  Input,
  List,
  Popconfirm,
  Popover,
  Select,
  Segmented,
  Skeleton,
  Switch,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createAssistantConversation,
  deleteAssistantConversation,
  getAssistantConversation,
  listAssistantConversations,
  renameAssistantConversation,
  sendAssistantMessage,
  updateAssistantConversation,
} from "../api/assistant";
import { listJobs } from "../api/jobs";
import { listResumes } from "../api/resumes";
import { useApi } from "../hooks/useApi";
import type {
  AssistantAttachmentInput,
  AssistantConversationDetail,
  AssistantAttachment,
  AssistantSource,
} from "../types";

const MAX_ATTACHMENT_COUNT = 4;
const MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024;
const MAX_TOTAL_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const IMAGE_MIME_BY_EXTENSION: Record<string, string> = {
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
interface StarterPrompt {
  label: string;
  content: string;
  enableWebSearch?: boolean;
}

const STARTER_PROMPTS: readonly StarterPrompt[] = [
  {
    label: "分析岗位匹配度",
    content: "请结合我选择的岗位和资料，分析我的匹配度，并给出准备建议。",
  },
  {
    label: "优化项目经历",
    content: "请帮我把我的项目经历改写得更贴合目标岗位，并保留真实事实。",
  },
  {
    label: "准备一轮面试",
    content: "请根据目标岗位模拟一轮面试，并逐题给出回答思路。",
  },
  {
    label: "查找招聘信息",
    content: "请帮我查找与目标方向相关的招聘信息，并优先给出官网链接。",
    enableWebSearch: true,
  },
] as const;

interface PendingAttachment extends AssistantAttachmentInput {
  id: number;
  size: number;
  kind: "text" | "image";
}

interface AttachmentClassification {
  kind: "text" | "image";
  mimeType: string;
}

function safeExternalUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function renderInlineMarkdown(value: string): ReactNode[] {
  const tokenPattern =
    /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<，。！？、）】〉》]+))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(value)) !== null) {
    if (match.index > cursor) nodes.push(value.slice(cursor, match.index));
    if (match[2]) {
      nodes.push(<strong key={`strong-${match.index}`}>{match[2]}</strong>);
    } else if (match[3]) {
      nodes.push(<code key={`code-${match.index}`}>{match[3]}</code>);
    } else {
      const url = safeExternalUrl(match[5] ?? match[6]);
      nodes.push(
        url ? (
          <a key={`link-${match.index}`} href={url} target="_blank" rel="noopener noreferrer">
            {match[4] ?? match[6]}
          </a>
        ) : (
          (match[4] ?? match[6])
        ),
      );
    }
    cursor = tokenPattern.lastIndex;
  }
  if (cursor < value.length) nodes.push(value.slice(cursor));
  return nodes;
}

function parseMarkdownTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return null;
  const source = trimmed.startsWith("|") ? trimmed.slice(1) : trimmed;
  const row = (source.endsWith("|") ? source.slice(0, -1) : source)
    .split("|")
    .map((cell) => cell.trim());
  return row.length >= 2 && row.every(Boolean) ? row : null;
}

function isMarkdownTableDivider(line: string, columnCount: number): boolean {
  const cells = parseMarkdownTableRow(line);
  return cells?.length === columnCount && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
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

function positiveId(value: string | null): number | undefined {
  return value && /^\d+$/.test(value) && Number(value) > 0 ? Number(value) : undefined;
}

function fileExtension(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

function classifyAttachment(file: File): AttachmentClassification | null {
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

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("读取附件失败"));
    reader.readAsDataURL(file);
  });
}

function ConversationTitle({
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

  const style = {
    "--assistant-title-scroll-distance": `-${overflowDistance}px`,
  } as CSSProperties;

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
          style={style}
        >
          <span>{title}</span>
        </span>
      </button>
    </Tooltip>
  );
}

function AssistantEmptyState({
  onChoosePrompt,
}: {
  onChoosePrompt: (prompt: (typeof STARTER_PROMPTS)[number]) => void;
}) {
  return (
    <div className="assistant-empty-state">
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <div className="assistant-empty-state-copy">
            <Typography.Text strong>可以这样问</Typography.Text>
            <Typography.Text type="secondary">
              可先关联岗位或简历，再按需开启资料和联网搜索。
            </Typography.Text>
          </div>
        }
      >
        <div className="assistant-starter-prompts" aria-label="常用求职提问">
          {STARTER_PROMPTS.map((prompt) => (
            <Button
              key={prompt.label}
              size="small"
              className="assistant-starter-prompt"
              onClick={() => onChoosePrompt(prompt)}
            >
              {prompt.label}
            </Button>
          ))}
        </div>
      </Empty>
    </div>
  );
}

function MessageAttachments({
  attachments,
}: {
  attachments: Array<AssistantAttachment | PendingAttachment>;
}) {
  if (!attachments.length) return null;
  return (
    <div className="assistant-message-attachments">
      {attachments.map((attachment, index) => {
        const dataUrl = "data_url" in attachment ? attachment.data_url : attachment.data;
        return attachment.kind === "image" && dataUrl ? (
          <Image
            key={`${attachment.name}-${index}`}
            src={dataUrl}
            alt={attachment.name}
            className="assistant-message-image"
          />
        ) : (
          <Tag key={`${attachment.name}-${index}`} icon={<FileTextOutlined />}>
            {attachment.name}
          </Tag>
        );
      })}
    </div>
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

export default function AssistantPage() {
  const { message } = App.useApp();
  const [searchParams] = useSearchParams();
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AssistantConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [content, setContent] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [jobId, setJobId] = useState<number | undefined>(() =>
    positiveId(searchParams.get("job_id")),
  );
  const [resumeId, setResumeId] = useState<number | undefined>(() =>
    positiveId(searchParams.get("resume_id")),
  );
  const [includeProfile, setIncludeProfile] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendingConversationId, setSendingConversationId] = useState<number | null>(null);
  const [attachmentReads, setAttachmentReads] = useState(0);
  const [pendingUserText, setPendingUserText] = useState("");
  const [pendingUserAttachments, setPendingUserAttachments] = useState<PendingAttachment[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [streamingSources, setStreamingSources] = useState<AssistantSource[]>([]);
  const [progressText, setProgressText] = useState("");
  const [streamError, setStreamError] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [actionMenuId, setActionMenuId] = useState<number | null>(null);
  const [conversationFilter, setConversationFilter] = useState<"all" | "favorite">("all");
  const abortRef = useRef<AbortController | null>(null);
  const activeIdRef = useRef<number | null>(null);
  const sendingRef = useRef(false);
  const mountedRef = useRef(true);
  const attachmentsRef = useRef<PendingAttachment[]>([]);
  const attachmentSequenceRef = useRef(0);
  const attachmentReadsRef = useRef(0);
  const attachmentUsageRef = useRef({ count: 0, bytes: 0 });
  const detailRequestRef = useRef(0);
  const messageEndRef = useRef<HTMLDivElement>(null);

  const selectConversation = useCallback((conversationId: number | null) => {
    activeIdRef.current = conversationId;
    setActiveId(conversationId);
  }, []);

  const clearAttachments = useCallback(() => {
    attachmentsRef.current = [];
    attachmentUsageRef.current = { count: attachmentReadsRef.current, bytes: 0 };
    setAttachments([]);
  }, []);

  const removeAttachment = useCallback((attachmentId: number) => {
    const attachment = attachmentsRef.current.find((item) => item.id === attachmentId);
    if (!attachment) return;
    const next = attachmentsRef.current.filter((item) => item.id !== attachmentId);
    attachmentsRef.current = next;
    attachmentUsageRef.current = {
      count: Math.max(attachmentReadsRef.current, attachmentUsageRef.current.count - 1),
      bytes: Math.max(0, attachmentUsageRef.current.bytes - attachment.size),
    };
    setAttachments(next);
  }, []);

  const {
    data: conversations,
    loading: conversationsLoading,
    error: conversationsError,
    reload: reloadConversations,
  } = useApi(listAssistantConversations, []);

  const { data: contextOptions } = useApi(async () => {
    const [jobs, resumes] = await Promise.all([
      listJobs({ page: 1, page_size: 100 }),
      listResumes({ page: 1, page_size: 100 }),
    ]);
    return { jobs: jobs.items, resumes: resumes.items };
  }, []);

  useEffect(() => {
    if (conversationsError) message.error(conversationsError);
  }, [conversationsError, message]);

  useEffect(() => {
    if (activeId || !conversations?.length) return;
    selectConversation(conversations[0].id);
  }, [activeId, conversations, selectConversation]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const loadDetail = useCallback(
    async (conversationId: number) => {
      const requestId = ++detailRequestRef.current;
      setDetailLoading(true);
      try {
        const next = await getAssistantConversation(conversationId);
        if (requestId === detailRequestRef.current) setDetail(next);
      } catch (error) {
        if (requestId === detailRequestRef.current) {
          setDetail(null);
          message.error(error instanceof Error ? error.message : "加载对话失败");
        }
      } finally {
        if (requestId === detailRequestRef.current) setDetailLoading(false);
      }
    },
    [message],
  );

  useEffect(() => {
    if (!activeId) {
      setDetail(null);
      return;
    }
    void loadDetail(activeId);
    return () => {
      detailRequestRef.current += 1;
    };
  }, [activeId, loadDetail]);

  const createConversation = async () => {
    try {
      const created = await createAssistantConversation();
      selectConversation(created.id);
      setDetail({ ...created, messages: [] });
      await reloadConversations();
      return created.id;
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建对话失败");
      return null;
    }
  };

  const removeConversation = async (id: number) => {
    try {
      await deleteAssistantConversation(id);
      if (activeId === id) {
        selectConversation(null);
        setDetail(null);
      }
      await reloadConversations();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除对话失败");
    }
  };

  const saveConversationTitle = async (id: number) => {
    const title = editingTitle.trim();
    if (!title) {
      message.warning("对话标题不能为空");
      return;
    }
    try {
      const updated = await renameAssistantConversation(id, title);
      setDetail((current) => (current?.id === id ? { ...current, title: updated.title } : current));
      setEditingId(null);
      await reloadConversations();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重命名失败");
    }
  };

  const updateConversationFlags = async (
    conversation: { id: number; pinned: boolean; favorite: boolean },
    field: "pinned" | "favorite",
  ) => {
    try {
      await updateAssistantConversation(conversation.id, {
        [field]: !conversation[field],
      });
      await reloadConversations();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "更新会话状态失败");
    }
  };

  const addAttachment = async (file: File) => {
    const classification = classifyAttachment(file);
    if (!classification) {
      message.warning("附件扩展名与文件类型不一致，或格式不受支持");
      return;
    }
    if (attachmentUsageRef.current.count >= MAX_ATTACHMENT_COUNT) {
      message.warning(`每条消息最多添加 ${MAX_ATTACHMENT_COUNT} 个附件`);
      return;
    }
    if (file.size > MAX_ATTACHMENT_BYTES) {
      message.warning(`单个附件不能超过 ${MAX_ATTACHMENT_BYTES / 1024 / 1024} MB`);
      return;
    }
    if (attachmentUsageRef.current.bytes + file.size > MAX_TOTAL_ATTACHMENT_BYTES) {
      message.warning(`附件总大小不能超过 ${MAX_TOTAL_ATTACHMENT_BYTES / 1024 / 1024} MB`);
      return;
    }

    // beforeUpload 会并行调用；先预留配额，避免多个慢速 FileReader 同时绕过上限。
    attachmentUsageRef.current = {
      count: attachmentUsageRef.current.count + 1,
      bytes: attachmentUsageRef.current.bytes + file.size,
    };
    attachmentReadsRef.current += 1;
    setAttachmentReads((current) => current + 1);
    try {
      const data = classification.kind === "image" ? await readAsDataUrl(file) : await file.text();
      if (!mountedRef.current) return;
      const attachment: PendingAttachment = {
        id: ++attachmentSequenceRef.current,
        name: file.name,
        mime_type: classification.mimeType,
        data,
        size: file.size,
        kind: classification.kind,
      };
      const next = [...attachmentsRef.current, attachment];
      attachmentsRef.current = next;
      setAttachments(next);
    } catch (error) {
      attachmentUsageRef.current = {
        count: Math.max(0, attachmentUsageRef.current.count - 1),
        bytes: Math.max(0, attachmentUsageRef.current.bytes - file.size),
      };
      message.error(error instanceof Error ? error.message : "读取附件失败");
    } finally {
      attachmentReadsRef.current = Math.max(0, attachmentReadsRef.current - 1);
      if (mountedRef.current) setAttachmentReads((current) => Math.max(0, current - 1));
    }
  };

  const send = async () => {
    const text = content.trim();
    if (
      (!text && attachmentsRef.current.length === 0) ||
      sendingRef.current ||
      attachmentReadsRef.current > 0
    ) {
      return;
    }
    sendingRef.current = true;
    setSending(true);

    const conversationId = activeIdRef.current ?? (await createConversation());
    if (!conversationId) {
      sendingRef.current = false;
      setSending(false);
      return;
    }

    const attachmentPayload = attachmentsRef.current.map(({ name, mime_type, data }) => ({
      name,
      mime_type,
      data,
    }));
    const optimisticAttachments = [...attachmentsRef.current];
    setContent("");
    setPendingUserText(text || "[附件]");
    setPendingUserAttachments(optimisticAttachments);
    setStreamingText("");
    setStreamingSources([]);
    setProgressText("");
    setStreamError("");
    setSendingConversationId(conversationId);
    clearAttachments();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await sendAssistantMessage(
        conversationId,
        {
          content: text,
          job_id: jobId,
          resume_id: resumeId,
          include_profile: includeProfile,
          web_search: webSearch,
          attachments: attachmentPayload,
        },
        (event) => {
          if (abortRef.current !== controller) return;
          if (event.type === "delta") setStreamingText((current) => current + event.text);
          if (event.type === "progress") setProgressText(event.message);
          if (event.type === "sources") {
            setStreamingSources(event.sources);
            if (event.error) setProgressText(event.error);
          }
          if (event.type === "error") setStreamError(event.message);
          if (event.type === "start") void reloadConversations();
        },
        controller.signal,
      );
    } catch (error) {
      if (!controller.signal.aborted) {
        setStreamError(error instanceof Error ? error.message : "发送消息失败");
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      sendingRef.current = false;
      if (mountedRef.current) {
        setSending(false);
        setPendingUserText("");
        setPendingUserAttachments([]);
        setStreamingText("");
        const refreshes: Promise<void>[] = [reloadConversations()];
        if (activeIdRef.current === conversationId) refreshes.push(loadDetail(conversationId));
        await Promise.all(refreshes);
      }
    }
  };

  const historyMessages = detail?.messages ?? [];
  const isActiveStream = activeId !== null && activeId === sendingConversationId;
  const hasActiveDetail = detail?.id === activeId;
  const showDetailLoading = detailLoading && !hasActiveDetail;
  const jobOptions = (contextOptions?.jobs ?? []).map((job) => ({
    value: job.id,
    label: `${job.company ? `${job.company} · ` : ""}${job.title}`,
  }));
  const resumeOptions = (contextOptions?.resumes ?? []).map((resume) => ({
    value: resume.id,
    label: resume.title,
  }));
  const visibleConversations = (conversations ?? []).filter((conversation) => {
    if (conversationFilter === "favorite") return conversation.favorite;
    return true;
  });

  const chooseStarterPrompt = (prompt: (typeof STARTER_PROMPTS)[number]) => {
    setContent(prompt.content);
    if (prompt.enableWebSearch) setWebSearch(true);
  };

  // 在浏览器绘制前定位到末尾，避免详情刷新时先闪现旧的顶部位置。
  useLayoutEffect(() => {
    if (showDetailLoading || (!historyMessages.length && !isActiveStream)) return;
    messageEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [detail?.id, detail?.messages, historyMessages.length, isActiveStream, showDetailLoading]);

  useEffect(() => {
    if (!sending || !isActiveStream) return;
    messageEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [
    isActiveStream,
    pendingUserText,
    progressText,
    sending,
    streamError,
    streamingSources,
    streamingText,
  ]);

  return (
    <div className="assistant-page">
      <aside className="assistant-sidebar">
        <Button
          type="primary"
          block
          icon={<PlusOutlined />}
          onClick={() => void createConversation()}
        >
          新对话
        </Button>
        <Segmented
          className="assistant-conversation-filter"
          block
          value={conversationFilter}
          options={[
            { label: "全部", value: "all" },
            { label: "收藏", value: "favorite" },
          ]}
          onChange={(value) => setConversationFilter(value as "all" | "favorite")}
        />
        <List
          className="assistant-conversation-list"
          loading={conversationsLoading}
          dataSource={visibleConversations}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话" />,
          }}
          renderItem={(conversation) => (
            <List.Item
              className={conversation.id === activeId ? "is-active" : ""}
              actions={[
                <Popover
                  key="more"
                  trigger="click"
                  placement="bottomRight"
                  open={actionMenuId === conversation.id}
                  onOpenChange={(open) => setActionMenuId(open ? conversation.id : null)}
                  content={
                    <div className="assistant-conversation-actions-menu">
                      <Button
                        type="text"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => {
                          setActionMenuId(null);
                          setEditingId(conversation.id);
                          setEditingTitle(conversation.title);
                        }}
                      >
                        重命名
                      </Button>
                      <Button
                        type="text"
                        size="small"
                        icon={conversation.pinned ? <PushpinFilled /> : <PushpinOutlined />}
                        onClick={() => {
                          setActionMenuId(null);
                          void updateConversationFlags(conversation, "pinned");
                        }}
                      >
                        {conversation.pinned ? "取消置顶" : "置顶对话"}
                      </Button>
                      <Button
                        type="text"
                        size="small"
                        icon={conversation.favorite ? <StarFilled /> : <StarOutlined />}
                        onClick={() => {
                          setActionMenuId(null);
                          void updateConversationFlags(conversation, "favorite");
                        }}
                      >
                        {conversation.favorite ? "取消收藏" : "收藏对话"}
                      </Button>
                      <Popconfirm
                        title="删除这段对话？"
                        onConfirm={() => {
                          setActionMenuId(null);
                          void removeConversation(conversation.id);
                        }}
                      >
                        <Button type="text" size="small" danger icon={<DeleteOutlined />}>
                          删除
                        </Button>
                      </Popconfirm>
                    </div>
                  }
                >
                  <Tooltip title="更多操作">
                    <Button
                      type="text"
                      size="small"
                      aria-label="更多对话操作"
                      className="assistant-conversation-more-button"
                      icon={<MoreOutlined />}
                    />
                  </Tooltip>
                </Popover>,
              ]}
            >
              {editingId === conversation.id ? (
                <Input
                  size="small"
                  value={editingTitle}
                  autoFocus
                  maxLength={128}
                  suffix={
                    <Button
                      type="text"
                      size="small"
                      aria-label="保存对话标题"
                      icon={<SaveOutlined />}
                      onClick={() => void saveConversationTitle(conversation.id)}
                    />
                  }
                  onChange={(event) => setEditingTitle(event.target.value)}
                  onPressEnter={() => void saveConversationTitle(conversation.id)}
                />
              ) : (
                <ConversationTitle
                  title={conversation.title}
                  pinned={conversation.pinned}
                  favorite={conversation.favorite}
                  onSelect={() => selectConversation(conversation.id)}
                />
              )}
            </List.Item>
          )}
        />
      </aside>

      <section className="assistant-workspace">
        <header className="assistant-header">
          <div>
            <Typography.Title level={3}>{detail?.title || "AI 求职助手"}</Typography.Title>
            <Typography.Text type="secondary">当前回复由「设置」中的模型配置提供。</Typography.Text>
          </div>
        </header>

        <div className="assistant-messages" aria-live="polite">
          {showDetailLoading ? (
            <Skeleton active paragraph={{ rows: 6 }} />
          ) : historyMessages.length === 0 && !(sending && isActiveStream) ? (
            <AssistantEmptyState onChoosePrompt={chooseStarterPrompt} />
          ) : (
            historyMessages.map((item) => (
              <article
                key={item.id}
                className={`assistant-message assistant-message--${item.role}`}
              >
                <Typography.Text strong>{item.role === "user" ? "你" : "求职助手"}</Typography.Text>
                <AssistantMessageContent content={item.content} />
                <MessageAttachments attachments={item.attachments} />
                <MessageSources sources={item.context.sources ?? []} />
                {item.status === "error" && item.error && (
                  <Alert type="error" message={item.error} />
                )}
              </article>
            ))
          )}
          {isActiveStream && (pendingUserText || pendingUserAttachments.length > 0) && (
            <article className="assistant-message assistant-message--user">
              <Typography.Text strong>你</Typography.Text>
              <AssistantMessageContent content={pendingUserText} />
              <MessageAttachments attachments={pendingUserAttachments} />
            </article>
          )}
          {isActiveStream && sending && (
            <article className="assistant-message assistant-message--assistant">
              <Typography.Text strong>求职助手</Typography.Text>
              <AssistantMessageContent content={streamingText || progressText || "正在思考…"} />
              <StreamingStatus
                message={streamingText ? "正在生成回答" : progressText || "正在准备回答"}
              />
              <MessageSources sources={streamingSources} />
            </article>
          )}
          {isActiveStream && streamError && <Alert type="error" showIcon message={streamError} />}
          <div ref={messageEndRef} />
        </div>

        <div className="assistant-composer">
          <div className="assistant-context-controls">
            <div className="assistant-context-selects">
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="关联岗位"
                value={jobId}
                options={jobOptions}
                onChange={setJobId}
              />
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="关联简历"
                value={resumeId}
                options={resumeOptions}
                onChange={setResumeId}
              />
            </div>
          </div>
          {(attachments.length > 0 || includeProfile) && (
            <Alert
              type="info"
              showIcon
              message="已选择的附件或个人资料会发送给当前配置的模型服务"
            />
          )}
          {attachments.length > 0 && (
            <div className="assistant-composer-attachments">
              {attachments.map((attachment) =>
                attachment.kind === "image" ? (
                  <div key={attachment.id} className="assistant-composer-image-item">
                    <Image
                      src={attachment.data}
                      alt={attachment.name}
                      className="assistant-message-image"
                    />
                    <Button
                      type="text"
                      size="small"
                      danger
                      aria-label={`移除附件 ${attachment.name}`}
                      onClick={() => removeAttachment(attachment.id)}
                    >
                      移除
                    </Button>
                  </div>
                ) : (
                  <Tag
                    key={attachment.id}
                    closable={!sending}
                    onClose={() => removeAttachment(attachment.id)}
                  >
                    {attachment.name}
                  </Tag>
                ),
              )}
            </div>
          )}
          <Input.TextArea
            value={content}
            autoSize={{ minRows: 3, maxRows: 8 }}
            disabled={sending}
            placeholder="输入求职、岗位、简历或项目经历相关问题"
            onChange={(event) => setContent(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <div className="assistant-composer-actions">
            <div className="assistant-composer-utility">
              <Upload
                accept=".txt,.md,.json,.csv,image/png,image/jpeg,image/webp,image/gif"
                multiple
                showUploadList={false}
                disabled={
                  sending || attachmentReads > 0 || attachments.length >= MAX_ATTACHMENT_COUNT
                }
                beforeUpload={(file) => {
                  void addAttachment(file as File);
                  return Upload.LIST_IGNORE;
                }}
              >
                <Tooltip title="添加文本或图片附件">
                  <Button
                    aria-label="添加附件"
                    icon={<PaperClipOutlined />}
                    loading={attachmentReads > 0}
                    disabled={sending || attachmentReads > 0}
                  >
                    附件
                  </Button>
                </Tooltip>
              </Upload>
              <div className="assistant-context-toggles">
                <label className="assistant-context-toggle">
                  <Switch size="small" checked={includeProfile} onChange={setIncludeProfile} />
                  <span>使用我的资料</span>
                </label>
                <label className="assistant-context-toggle">
                  <Switch size="small" checked={webSearch} onChange={setWebSearch} />
                  <span>联网搜索</span>
                </label>
              </div>
            </div>
            {sending ? (
              <Button
                danger
                aria-label="停止生成"
                icon={<StopOutlined />}
                onClick={() => abortRef.current?.abort()}
              >
                停止
              </Button>
            ) : (
              <Button
                type="primary"
                aria-label="发送消息"
                icon={<SendOutlined />}
                disabled={attachmentReads > 0 || (!content.trim() && attachments.length === 0)}
                onClick={() => void send()}
              >
                发送
              </Button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
