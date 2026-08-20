/** AI 求职助手：流式对话、历史记录、附件与项目上下文联动。 */
import {
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  PaperClipOutlined,
  PlusOutlined,
  SaveOutlined,
  SendOutlined,
  StopOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Empty,
  Input,
  List,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createAssistantConversation,
  deleteAssistantConversation,
  getAssistantConversation,
  listAssistantConversations,
  renameAssistantConversation,
  sendAssistantMessage,
} from "../api/assistant";
import { listJobs } from "../api/jobs";
import { listResumes } from "../api/resumes";
import { useApi } from "../hooks/useApi";
import type {
  AssistantAttachmentInput,
  AssistantConversationDetail,
  AssistantMessage,
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

interface PendingAttachment extends AssistantAttachmentInput {
  id: number;
  size: number;
  kind: "text" | "image";
}

interface AttachmentClassification {
  kind: "text" | "image";
  mimeType: string;
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

function MessageAttachments({ message }: { message: AssistantMessage }) {
  if (!message.attachments.length) return null;
  return (
    <div className="assistant-message-attachments">
      {message.attachments.map((attachment, index) =>
        attachment.kind === "image" && attachment.data_url ? (
          <img
            key={`${attachment.name}-${index}`}
            src={attachment.data_url}
            alt={attachment.name}
            className="assistant-message-image"
          />
        ) : (
          <Tag key={`${attachment.name}-${index}`} icon={<FileTextOutlined />}>
            {attachment.name}
          </Tag>
        ),
      )}
    </div>
  );
}

function MessageSources({ sources }: { sources: AssistantSource[] }) {
  if (!sources.length) return null;
  return (
    <div className="assistant-sources">
      <Typography.Text type="secondary">参考来源</Typography.Text>
      {sources.map((source) => (
        <Typography.Link
          key={source.url}
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          {source.title || source.url}
        </Typography.Link>
      ))}
    </div>
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
  const [streamingText, setStreamingText] = useState("");
  const [streamingSources, setStreamingSources] = useState<AssistantSource[]>([]);
  const [progressText, setProgressText] = useState("");
  const [streamError, setStreamError] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
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

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: sending ? "auto" : "smooth" });
  }, [detail?.messages, pendingUserText, sending, streamingText]);

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
    setContent("");
    setPendingUserText(text || "[附件]");
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
        setStreamingText("");
        const refreshes: Promise<void>[] = [reloadConversations()];
        if (activeIdRef.current === conversationId) refreshes.push(loadDetail(conversationId));
        await Promise.all(refreshes);
      }
    }
  };

  const historyMessages = detail?.messages ?? [];
  const isActiveStream = activeId !== null && activeId === sendingConversationId;
  const jobOptions = (contextOptions?.jobs ?? []).map((job) => ({
    value: job.id,
    label: `${job.company ? `${job.company} · ` : ""}${job.title}`,
  }));
  const resumeOptions = (contextOptions?.resumes ?? []).map((resume) => ({
    value: resume.id,
    label: resume.title,
  }));

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
        <List
          className="assistant-conversation-list"
          loading={conversationsLoading}
          dataSource={conversations ?? []}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话" />,
          }}
          renderItem={(conversation) => (
            <List.Item
              className={conversation.id === activeId ? "is-active" : ""}
              actions={[
                <Tooltip title="重命名" key="rename">
                  <Button
                    type="text"
                    size="small"
                    aria-label="重命名对话"
                    icon={<EditOutlined />}
                    onClick={() => {
                      setEditingId(conversation.id);
                      setEditingTitle(conversation.title);
                    }}
                  />
                </Tooltip>,
                <Popconfirm
                  key="delete"
                  title="删除这段对话？"
                  onConfirm={() => void removeConversation(conversation.id)}
                >
                  <Tooltip title="删除">
                    <Button
                      type="text"
                      size="small"
                      danger
                      aria-label="删除对话"
                      icon={<DeleteOutlined />}
                    />
                  </Tooltip>
                </Popconfirm>,
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
                <button
                  type="button"
                  className="assistant-conversation-button"
                  onClick={() => selectConversation(conversation.id)}
                >
                  {conversation.title}
                </button>
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
          {detailLoading ? (
            <Skeleton active paragraph={{ rows: 6 }} />
          ) : historyMessages.length === 0 && !(sending && isActiveStream) ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="开始一段求职对话" />
          ) : (
            historyMessages.map((item) => (
              <article
                key={item.id}
                className={`assistant-message assistant-message--${item.role}`}
              >
                <Typography.Text strong>{item.role === "user" ? "你" : "求职助手"}</Typography.Text>
                <div className="assistant-message-content">{item.content}</div>
                <MessageAttachments message={item} />
                <MessageSources sources={item.context.sources ?? []} />
                {item.status === "error" && item.error && (
                  <Alert type="error" message={item.error} />
                )}
              </article>
            ))
          )}
          {isActiveStream && pendingUserText && (
            <article className="assistant-message assistant-message--user">
              <Typography.Text strong>你</Typography.Text>
              <div className="assistant-message-content">{pendingUserText}</div>
            </article>
          )}
          {isActiveStream && sending && (
            <article className="assistant-message assistant-message--assistant">
              <Typography.Text strong>求职助手</Typography.Text>
              <div className="assistant-message-content">
                {streamingText || progressText || "正在思考…"}
              </div>
              <MessageSources sources={streamingSources} />
            </article>
          )}
          {isActiveStream && streamError && <Alert type="error" showIcon message={streamError} />}
          <div ref={messageEndRef} />
        </div>

        <div className="assistant-composer">
          <div className="assistant-context-controls">
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
            <Space size={6}>
              <Switch size="small" checked={includeProfile} onChange={setIncludeProfile} />
              <Typography.Text>使用我的资料</Typography.Text>
            </Space>
            <Space size={6}>
              <Switch size="small" checked={webSearch} onChange={setWebSearch} />
              <Typography.Text>联网搜索</Typography.Text>
            </Space>
          </div>
          {(attachments.length > 0 || includeProfile) && (
            <Alert
              type="info"
              showIcon
              message="已选择的附件或个人资料会发送给当前配置的模型服务"
            />
          )}
          {attachments.length > 0 && (
            <Space wrap>
              {attachments.map((attachment) => (
                <Tag
                  key={attachment.id}
                  closable={!sending}
                  onClose={() => removeAttachment(attachment.id)}
                >
                  {attachment.name}
                </Tag>
              ))}
            </Space>
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
