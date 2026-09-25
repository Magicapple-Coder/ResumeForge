/** 求职助手会话列表、详情加载与会话管理操作。 */

import { App } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  createAssistantConversation,
  deleteAssistantConversation,
  forkAssistantConversation,
  getAssistantConversation,
  listAssistantConversations,
  renameAssistantConversation,
  updateAssistantConversation,
} from "../../../api/assistant";
import { listJobs } from "../../../api/jobs";
import { listResumes } from "../../../api/resumes";
import { useApi } from "../../../hooks/useApi";
import { hasShownAssistantWelcome, markAssistantWelcomeShown } from "../welcomeGate";
import type { AssistantConversationDetail, AssistantConversationBrief } from "../../../types";

interface Options {
  message: ReturnType<typeof App.useApp>["message"];
  /** 为真时进入「新对话」模式：不自动恢复最近会话（由页面负责新建空会话）。 */
  /** 是否以"新对话"进入（`?new=1`）。会话钩子不再用它——草稿状态由页面侧决定；
   *  保留参数是为了不打断调用方签名，也留下"这个入口存在"的痕迹。 */
  startNew?: boolean;
}

/** 会话可以被单独修改的字段（置顶/收藏/归档/分组名）。 */
export type ConversationPatch = Partial<
  Pick<AssistantConversationBrief, "pinned" | "favorite" | "archived" | "group_name">
>;

export function useAssistantConversations({ message }: Options) {
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AssistantConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const activeIdRef = useRef<number | null>(null);
  const detailRequestRef = useRef(0);
  const welcomeRequestedRef = useRef(false);

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

  const selectConversation = useCallback((conversationId: number | null) => {
    activeIdRef.current = conversationId;
    setActiveId(conversationId);
  }, []);

  /**
   * 进入"草稿"对话：界面上是一段可以马上写的空对话，**数据库里什么都不建**。
   *
   * 记录由第一次发送时懒创建（见 `useAssistantStream.send`）。这样"点进来看看、
   * 什么都没写就退出"不会留下一堆空对话——用户明确要求过这一点。
   */
  const startDraft = useCallback(() => {
    selectConversation(null);
    setDetail(null);
  }, [selectConversation]);

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
    if (conversationsError) message.error(conversationsError);
  }, [conversationsError, message]);

  // 进入助手页**不再自动打开最近那条会话**：用户要的是"点进来就是一段可以马上写的新对话"，
  // 记录由第一次发送时懒创建（见 useAssistantStream.send）。历史会话仍在左侧列表里，
  // 点一下就切过去；?conversation= 深链也照旧能直接定位。
  // （以前这里会自动选中 conversations[0]，于是每次进来先看到上次的对话。）

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

  const createConversation = useCallback(async () => {
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
  }, [message, reloadConversations, selectConversation]);

  /**
   * 内置引导对话：**第一次**用助手且一条会话都没有时，自动建一条带欢迎消息的会话。
   *
   * 两道闸：`welcomeRequestedRef` 挡住同一次挂载里的重复调用（创建失败也不循环重试，
   * 否则一个持续报错的后端会让页面不停发请求），`hasShownAssistantWelcome()` 挡住
   * 跨挂载的重复——不然用户删光会话后每次回到这一页都会被再塞一条。
   */
  const ensureWelcomeConversation = useCallback(async () => {
    if (welcomeRequestedRef.current) return;
    welcomeRequestedRef.current = true;
    if (hasShownAssistantWelcome()) return;
    try {
      const created = await createAssistantConversation("", { welcome: true });
      markAssistantWelcomeShown();
      selectConversation(created.id);
      await loadDetail(created.id);
      await reloadConversations();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建引导对话失败");
    }
  }, [loadDetail, message, reloadConversations, selectConversation]);

  const removeConversation = useCallback(
    async (id: number) => {
      try {
        await deleteAssistantConversation(id);
        if (activeIdRef.current === id) {
          selectConversation(null);
          setDetail(null);
        }
        await reloadConversations();
      } catch (error) {
        message.error(error instanceof Error ? error.message : "删除对话失败");
      }
    },
    [message, reloadConversations, selectConversation],
  );

  const saveConversationTitle = useCallback(
    async (id: number, nextTitle: string) => {
      const title = nextTitle.trim();
      if (!title) {
        message.warning("对话标题不能为空");
        return;
      }
      try {
        const updated = await renameAssistantConversation(id, title);
        setDetail((current) =>
          current?.id === id ? { ...current, title: updated.title } : current,
        );
        await reloadConversations();
      } catch (error) {
        message.error(error instanceof Error ? error.message : "重命名失败");
      }
    },
    [message, reloadConversations],
  );

  const updateConversation = useCallback(
    async (id: number, patch: ConversationPatch) => {
      try {
        const updated = await updateAssistantConversation(id, patch);
        setDetail((current) => (current?.id === id ? { ...current, ...updated } : current));
        await reloadConversations();
        return updated;
      } catch (error) {
        message.error(error instanceof Error ? error.message : "更新会话失败");
        return null;
      }
    },
    [message, reloadConversations],
  );

  /** 兼容旧调用点：切换置顶/收藏。 */
  const updateConversationFlags = useCallback(
    async (
      conversation: Pick<AssistantConversationBrief, "id" | "pinned" | "favorite">,
      field: "pinned" | "favorite",
    ) => {
      await updateConversation(conversation.id, { [field]: !conversation[field] });
    },
    [updateConversation],
  );

  /** 「在新对话中继续」：复制最近若干条消息到一段新会话并切过去。 */
  const forkConversation = useCallback(
    async (id: number) => {
      try {
        const created = await forkAssistantConversation(id, {
          message_limit: 10,
          title: `${(conversations ?? []).find((item) => item.id === id)?.title ?? ""}（续）`,
        });
        selectConversation(created.id);
        setDetail(created);
        await reloadConversations();
        return created.id;
      } catch (error) {
        message.error(error instanceof Error ? error.message : "在新对话中继续失败");
        return null;
      }
    },
    [conversations, message, reloadConversations, selectConversation],
  );

  return {
    startDraft,
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
  };
}
