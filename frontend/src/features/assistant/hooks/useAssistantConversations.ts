/** 求职助手会话列表、详情加载与会话管理操作。 */

import { App } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  createAssistantConversation,
  deleteAssistantConversation,
  getAssistantConversation,
  listAssistantConversations,
  renameAssistantConversation,
  updateAssistantConversation,
} from "../../../api/assistant";
import { listJobs } from "../../../api/jobs";
import { listResumes } from "../../../api/resumes";
import { useApi } from "../../../hooks/useApi";
import type { AssistantConversationDetail, AssistantConversationBrief } from "../../../types";

interface Options {
  message: ReturnType<typeof App.useApp>["message"];
}

export function useAssistantConversations({ message }: Options) {
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AssistantConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const activeIdRef = useRef<number | null>(null);
  const detailRequestRef = useRef(0);

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

  useEffect(() => {
    if (activeId || !conversations?.length) return;
    selectConversation(conversations[0].id);
  }, [activeId, conversations, selectConversation]);

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

  const updateConversationFlags = useCallback(
    async (
      conversation: Pick<AssistantConversationBrief, "id" | "pinned" | "favorite">,
      field: "pinned" | "favorite",
    ) => {
      try {
        await updateAssistantConversation(conversation.id, { [field]: !conversation[field] });
        await reloadConversations();
      } catch (error) {
        message.error(error instanceof Error ? error.message : "更新会话状态失败");
      }
    },
    [message, reloadConversations],
  );

  return {
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
  };
}
