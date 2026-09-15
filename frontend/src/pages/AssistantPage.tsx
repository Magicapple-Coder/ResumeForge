/** AI 求职助手：流式对话、历史记录、附件与项目上下文联动。 */
import { App, Typography } from "antd";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import AssistantComposer from "../features/assistant/components/AssistantComposer";
import AssistantMessageList from "../features/assistant/components/AssistantMessageList";
import ConversationSidebar from "../features/assistant/components/ConversationSidebar";
import type { StarterPrompt } from "../features/assistant/assistantTypes";
import { positiveId } from "../features/assistant/assistantUtils";
import { useAssistantAttachments } from "../features/assistant/hooks/useAssistantAttachments";
import { useAssistantConversations } from "../features/assistant/hooks/useAssistantConversations";
import { useAssistantStream } from "../features/assistant/hooks/useAssistantStream";

export {
  AssistantMessageContent,
  MessageSources,
  StreamingStatus,
} from "../features/assistant/components/AssistantMessageContent";

export default function AssistantPage() {
  const { message } = App.useApp();
  const [searchParams] = useSearchParams();
  const [content, setContent] = useState("");
  const [jobId, setJobId] = useState<number | undefined>(() =>
    positiveId(searchParams.get("job_id")),
  );
  const [resumeId, setResumeId] = useState<number | undefined>(() =>
    positiveId(searchParams.get("resume_id")),
  );
  const [includeProfile, setIncludeProfile] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const mountedRef = useRef(true);
  const messageEndRef = useRef<HTMLDivElement>(null);
  const conversationsState = useAssistantConversations({ message });
  const {
    activeId,
    activeIdRef,
    detail,
    detailLoading,
    conversations,
    conversationsLoading,
    contextOptions,
    reloadConversations,
    loadDetail,
    selectConversation,
    createConversation,
    removeConversation,
    saveConversationTitle,
    updateConversationFlags,
  } = conversationsState;
  const attachmentsState = useAssistantAttachments({ mountedRef });
  const {
    attachments,
    attachmentsRef,
    attachmentReads,
    attachmentReadsRef,
    clearAttachments,
    removeAttachment,
    addAttachment,
  } = attachmentsState;
  const stream = useAssistantStream({
    activeIdRef,
    reloadConversations,
    loadDetail,
    createConversation,
    clearAttachments,
    attachmentReadsRef,
    attachmentsRef,
    mountedRef,
    jobId,
    resumeId,
    includeProfile,
    webSearch,
  });
  const {
    sending,
    sendingConversationId,
    pendingUserText,
    pendingUserAttachments,
    streamingText,
    streamingSources,
    streamingTools,
    progressText,
    streamError,
    send,
    stop,
  } = stream;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stop();
    };
  }, [stop]);

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
  const chooseStarterPrompt = (prompt: StarterPrompt) => {
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
    streamingTools,
    streamingText,
  ]);

  return (
    <div className="assistant-page">
      <ConversationSidebar
        conversations={conversations}
        loading={conversationsLoading}
        activeId={activeId}
        onCreate={() => void createConversation()}
        onSelect={selectConversation}
        onDelete={(id) => void removeConversation(id)}
        onRename={(id, title) => void saveConversationTitle(id, title)}
        onToggleFlag={(conversation, field) => void updateConversationFlags(conversation, field)}
      />
      <section className="assistant-workspace">
        <header className="assistant-header">
          <div>
            <Typography.Title level={3}>{detail?.title || "AI 求职助手"}</Typography.Title>
            <Typography.Text type="secondary">当前回复由「设置」中的模型配置提供。</Typography.Text>
          </div>
        </header>
        <AssistantMessageList
          detail={detail}
          showLoading={showDetailLoading}
          activeStream={isActiveStream}
          sending={sending}
          pendingUserText={pendingUserText}
          pendingUserAttachments={pendingUserAttachments}
          streamingText={streamingText}
          streamingSources={streamingSources}
          streamingTools={streamingTools}
          progressText={progressText}
          streamError={streamError}
          messageEndRef={messageEndRef}
          onChoosePrompt={chooseStarterPrompt}
        />
        <AssistantComposer
          content={content}
          attachments={attachments}
          sending={sending}
          attachmentReads={attachmentReads}
          jobId={jobId}
          resumeId={resumeId}
          includeProfile={includeProfile}
          webSearch={webSearch}
          jobOptions={jobOptions}
          resumeOptions={resumeOptions}
          onContentChange={setContent}
          onJobChange={setJobId}
          onResumeChange={setResumeId}
          onIncludeProfileChange={setIncludeProfile}
          onWebSearchChange={setWebSearch}
          onAddAttachment={(file) => void addAttachment(file)}
          onRemoveAttachment={removeAttachment}
          onSend={() => void send(content, () => setContent(""))}
          onStop={stop}
        />
      </section>
    </div>
  );
}
