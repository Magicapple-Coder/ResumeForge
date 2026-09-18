/** AI 求职助手：流式对话、历史记录、技能开关、附件与项目上下文联动。 */
import { CheckSquareOutlined, CloseOutlined, DeleteOutlined } from "@ant-design/icons";
import { App, Button, Input, Modal, Space, Typography } from "antd";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { deleteAssistantMessage, deleteAssistantMessages } from "../api/assistant";
import AssistantComposer from "../features/assistant/components/AssistantComposer";
import AssistantMessageList from "../features/assistant/components/AssistantMessageList";
import ConversationSidebar from "../features/assistant/components/ConversationSidebar";
import type { StarterPrompt } from "../features/assistant/assistantTypes";
import { positiveId } from "../features/assistant/assistantUtils";
import { markAssistantWelcomeShown } from "../features/assistant/welcomeGate";
import { useAssistantAttachments } from "../features/assistant/hooks/useAssistantAttachments";
import { useAssistantConversations } from "../features/assistant/hooks/useAssistantConversations";
import { useAssistantSkills } from "../features/assistant/hooks/useAssistantSkills";
import { useAssistantStream } from "../features/assistant/hooks/useAssistantStream";
import type {
  AssistantConversationBrief,
  AssistantMessage,
  AssistantQuotedMessage,
  ReasoningEffort,
} from "../types";

export {
  AssistantMessageContent,
  MessageSources,
  StreamingStatus,
} from "../features/assistant/components/AssistantMessageContent";

/** 思考强度是本机偏好，跟着浏览器而不是数据库走（换数据集时不该被重置）。 */
const REASONING_EFFORT_STORAGE_KEY = "resumeforge.assistant.reasoning_effort";

function readStoredEffort(): ReasoningEffort {
  const raw = window.localStorage.getItem(REASONING_EFFORT_STORAGE_KEY) ?? "";
  return (["", "none", "low", "medium", "high"] as const).includes(raw as ReasoningEffort)
    ? (raw as ReasoningEffort)
    : "";
}

export default function AssistantPage() {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
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
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>(readStoredEffort);
  const [groupTarget, setGroupTarget] = useState<AssistantConversationBrief | null>(null);
  const [groupValue, setGroupValue] = useState("");
  /** 多选删除：进入后每条消息左侧出勾选框，可一次删掉几条。 */
  const [selecting, setSelecting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<number>>(() => new Set());
  const mountedRef = useRef(true);
  const messageEndRef = useRef<HTMLDivElement>(null);
  /** 深链已经定位过的会话 id：只认一次，之后列表怎么刷新都不再抢焦点。 */
  const deepLinkAppliedRef = useRef<number | null>(null);
  const requestedConversationId = positiveId(searchParams.get("conversation"));
  const conversationsState = useAssistantConversations({ message });
  const {
    activeId,
    activeIdRef,
    detail,
    detailLoading,
    conversations,
    conversationsLoading,
    conversationsError,
    contextOptions,
    reloadConversations,
    loadDetail,
    selectConversation,
    createConversation,
    ensureWelcomeConversation,
    removeConversation,
    saveConversationTitle,
    updateConversation,
    updateConversationFlags,
    forkConversation,
  } = conversationsState;
  const { skills, enabledSkills, skillsLoaded, togglingSkillId, toggleSkill, reloadSkills } =
    useAssistantSkills();
  const openSkillWorkbench = () => navigate("/skills");
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
  // 引用追问：右键消息「引用这条继续问」后出现，只对下一次提问有效。
  const [quoted, setQuoted] = useState<AssistantQuotedMessage | null>(null);
  const clearQuote = useCallback(() => setQuoted(null), []);

  const quoteMessage = useCallback(
    (target: AssistantMessage) => {
      setQuoted({
        id: target.id,
        role: target.role,
        // 与后端快照保持同样的截断长度，避免引用块里显示的长度前后不一致。
        excerpt: target.content.trim().slice(0, 500) || "[附件消息]",
      });
      message.info("已引用这条消息，输入你的追问即可");
    },
    [message],
  );

  const removeMessage = useCallback(
    async (target: AssistantMessage) => {
      if (!activeId) return;
      try {
        await deleteAssistantMessage(activeId, target.id);
        await loadDetail(activeId);
        message.success("消息已删除");
      } catch (error) {
        message.error(error instanceof Error ? error.message : "删除消息失败");
      }
    },
    [activeId, loadDetail, message],
  );

  const exitSelecting = useCallback(() => {
    setSelecting(false);
    setSelectedIds(new Set());
  }, []);

  const messageCount = detail?.messages.length ?? 0;

  // 换会话就退出多选：勾着的是上一条会话的消息 id，留着会让新会话里 id 相同的消息
  // 出现在"已选"里，一点删除就删错了。
  useEffect(() => {
    exitSelecting();
  }, [activeId, exitSelecting]);

  const toggleSelected = useCallback((target: AssistantMessage) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(target.id)) next.delete(target.id);
      else next.add(target.id);
      return next;
    });
  }, []);

  /**
   * 多选删除。
   *
   * 一条都不选时按钮是禁用的，所以这里不用处理空集合；后端在 `message_ids` 为空时
   * 会直接 422（它要求至少一条）。删除后退出多选态：留着勾选状态而那条消息已经不见了，
   * 再点删除会把一批旧 id 发过去。
   */
  const removeSelected = useCallback(async () => {
    if (!activeId || selectedIds.size === 0) return;
    try {
      const { deleted } = await deleteAssistantMessages(activeId, [...selectedIds]);
      await loadDetail(activeId);
      exitSelecting();
      message.success(`已删除 ${deleted} 条消息`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除消息失败");
    }
  }, [activeId, exitSelecting, loadDetail, message, selectedIds]);

  const stream = useAssistantStream({
    activeIdRef,
    reloadConversations,
    loadDetail,
    createConversation,
    clearAttachments,
    attachmentReadsRef,
    attachmentsRef,
    mountedRef,
    quotedMessageId: quoted?.id ?? null,
    clearQuote,
    jobId,
    resumeId,
    includeProfile,
    webSearch,
    reasoningEffort,
  });
  const {
    sending,
    sendingConversationId,
    pendingUserText,
    pendingSentAt,
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

  // 思考强度：切一次记一次，下次打开助手页沿用上次的选择。
  useEffect(() => {
    window.localStorage.setItem(REASONING_EFFORT_STORAGE_KEY, reasoningEffort);
  }, [reasoningEffort]);

  // 深链：从「复制分享链接」打开时直接定位到那一段对话。
  //
  // **只认一次**：会话列表每次刷新都是一个新数组，而这个 effect 依赖它。不加这道判断的话，
  // 用户点开深链后再切到别的会话，只要发生任何刷新（发消息、重命名、归档、删除……）就会被
  // 拽回深链那一条，正在流式的回复也跟着消失。换一个 conversation 参数时仍然会重新定位。
  useEffect(() => {
    if (requestedConversationId === undefined || conversationsLoading) return;
    if (deepLinkAppliedRef.current === requestedConversationId) return;
    if (conversations === undefined) return;
    deepLinkAppliedRef.current = requestedConversationId;
    if (!conversations.some((item) => item.id === requestedConversationId)) {
      // 链接指向的会话不在已加载的列表里（列表只取最近 100 条）。静默不响应会让用户
      // 以为链接坏了，所以明说一次。
      message.info("链接里的对话不在当前列表中，可能超出了最近 100 条对话的范围。");
      return;
    }
    selectConversation(requestedConversationId);
  }, [conversations, conversationsLoading, message, requestedConversationId, selectConversation]);

  // 首次进入且一条会话都没有：自动创建带欢迎消息的引导对话。
  useEffect(() => {
    if (conversationsLoading || conversationsError || requestedConversationId !== undefined) {
      return;
    }
    // 列表还没回来时 `conversations` 是 undefined，"空"和"没加载"必须分开——
    // 请求失败也走这条分支的话，会因为一次网络抖动就多建一条引导对话。
    if (conversations === undefined) return;
    if (conversations.length > 0) {
      // 已经有会话，说明引导这一步早就过去了；记下来，免得用户以后删光会话时又冒出来。
      markAssistantWelcomeShown();
      return;
    }
    void ensureWelcomeConversation();
  }, [
    conversations,
    conversationsError,
    conversationsLoading,
    ensureWelcomeConversation,
    requestedConversationId,
  ]);

  const historyMessages = detail?.messages ?? [];
  const isActiveStream = activeId !== null && activeId === sendingConversationId;
  const hasActiveDetail = detail?.id === activeId;
  // "还没有会话"和"会话还在加载"在详情为空时长得一样，但只有后者该显示骨架屏。分不清的话
  // 空态会先画出来、被骨架屏顶掉、再画回来（实测每次进入都闪一下）。
  const hasNoConversations = !conversationsLoading && (conversations?.length ?? 0) === 0;
  const awaitingConversation =
    !hasNoConversations && (detail === null || (detailLoading && !hasActiveDetail));
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

  const handleToggleSkill = useCallback(
    async (skill: (typeof skills)[number], enabled: boolean) => {
      try {
        await toggleSkill(skill, enabled);
        message.success(`已${enabled ? "启用" : "停用"}技能「${skill.name}」`);
      } catch (error) {
        message.error(error instanceof Error ? error.message : "切换技能失败");
        await reloadSkills();
      }
    },
    [message, reloadSkills, toggleSkill],
  );

  const openGroupModal = (conversation: AssistantConversationBrief) => {
    setGroupTarget(conversation);
    setGroupValue(conversation.group_name);
  };

  const confirmGroup = async () => {
    if (!groupTarget) return;
    const updated = await updateConversation(groupTarget.id, { group_name: groupValue.trim() });
    if (updated) {
      message.success(groupValue.trim() ? `已移动到「${groupValue.trim()}」` : "已移出分组");
      setGroupTarget(null);
    }
  };

  // 在浏览器绘制前定位到末尾，避免详情刷新时先闪现旧的顶部位置。
  useLayoutEffect(() => {
    if (awaitingConversation || (!historyMessages.length && !isActiveStream)) return;
    messageEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [awaitingConversation, detail?.id, detail?.messages, historyMessages.length, isActiveStream]);

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
        onArchive={(conversation, archived) =>
          void updateConversation(conversation.id, { archived })
        }
        onFork={(conversation) => void forkConversation(conversation.id)}
        onMoveToGroup={openGroupModal}
      />
      <section className="assistant-workspace">
        <header className="assistant-header">
          <div className="assistant-header-titles">
            <Typography.Title level={3} ellipsis={{ tooltip: true }}>
              {detail?.title || "AI 求职助手"}
            </Typography.Title>
            <Typography.Text type="secondary">当前回复由「设置」中的模型配置提供。</Typography.Text>
          </div>
          {/* 多选只在有历史消息时才有意义；流式回复期间也不给进——那两条临时气泡还不在
              数据库里，勾不上。 */}
          {messageCount > 0 && !selecting && (
            <Button
              icon={<CheckSquareOutlined />}
              disabled={sending}
              onClick={() => setSelecting(true)}
            >
              多选
            </Button>
          )}
        </header>
        {selecting && (
          <div className="assistant-select-bar">
            <Typography.Text type="secondary">已选 {selectedIds.size} 条</Typography.Text>
            <Space size={8}>
              <Button
                danger
                size="small"
                icon={<DeleteOutlined />}
                disabled={selectedIds.size === 0}
                onClick={() =>
                  modal.confirm({
                    title: `删除选中的 ${selectedIds.size} 条消息？`,
                    content: "删除后无法恢复。引用这些消息的提问仍会保留引用内容。",
                    okText: "删除",
                    okButtonProps: { danger: true },
                    cancelText: "取消",
                    onOk: () => removeSelected(),
                  })
                }
              >
                删除所选
              </Button>
              <Button size="small" icon={<CloseOutlined />} onClick={exitSelecting}>
                退出多选
              </Button>
            </Space>
          </div>
        )}
        <AssistantMessageList
          detail={detail}
          showLoading={awaitingConversation}
          activeStream={isActiveStream}
          sending={sending}
          pendingUserText={pendingUserText}
          pendingSentAt={pendingSentAt}
          pendingUserAttachments={pendingUserAttachments}
          streamingText={streamingText}
          streamingSources={streamingSources}
          streamingTools={streamingTools}
          progressText={progressText}
          streamError={streamError}
          messageEndRef={messageEndRef}
          enabledSkillCount={enabledSkills.length}
          skillsLoaded={skillsLoaded}
          onChoosePrompt={chooseStarterPrompt}
          onManageSkills={openSkillWorkbench}
          onQuote={quoteMessage}
          onDeleteMessage={(target) => void removeMessage(target)}
          selecting={selecting}
          selectedIds={selectedIds}
          onToggleSelected={toggleSelected}
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
          reasoningEffort={reasoningEffort}
          skills={skills}
          skillsLoaded={skillsLoaded}
          togglingSkillId={togglingSkillId}
          jobOptions={jobOptions}
          resumeOptions={resumeOptions}
          onContentChange={setContent}
          onJobChange={setJobId}
          onResumeChange={setResumeId}
          onIncludeProfileChange={setIncludeProfile}
          onWebSearchChange={setWebSearch}
          onReasoningEffortChange={setReasoningEffort}
          onToggleSkill={(skill, enabled) => void handleToggleSkill(skill, enabled)}
          onManageSkills={openSkillWorkbench}
          onAddAttachment={(file) => void addAttachment(file)}
          onRemoveAttachment={removeAttachment}
          quoted={quoted}
          onClearQuote={clearQuote}
          onSend={() => void send(content, () => setContent(""))}
          onStop={stop}
        />
      </section>
      <Modal
        title="移动到分组"
        open={groupTarget !== null}
        okText="保存"
        onCancel={() => setGroupTarget(null)}
        onOk={() => void confirmGroup()}
      >
        <Typography.Paragraph type="secondary">
          给这段对话归个类（例如「字节」「面试准备」）。留空表示移出分组。分组只影响侧栏的显示，不会动对话内容。
        </Typography.Paragraph>
        <Input
          value={groupValue}
          maxLength={64}
          placeholder="分组名称"
          onChange={(event) => setGroupValue(event.target.value)}
        />
      </Modal>
    </div>
  );
}
