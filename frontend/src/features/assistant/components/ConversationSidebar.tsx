/** 求职助手会话列表、筛选和按需显示的管理操作。 */

import {
  DeleteOutlined,
  EditOutlined,
  MoreOutlined,
  PlusOutlined,
  PushpinFilled,
  PushpinOutlined,
  SaveOutlined,
  StarFilled,
  StarOutlined,
} from "@ant-design/icons";
import { Button, Empty, Input, List, Popconfirm, Popover, Segmented, Tooltip } from "antd";
import { useState } from "react";
import type { AssistantConversationBrief } from "../../../types";
import { type ConversationFilter } from "../assistantTypes";
import { ConversationTitle } from "./AssistantMessageContent";

interface Props {
  conversations: AssistantConversationBrief[] | undefined;
  loading: boolean;
  activeId: number | null;
  onCreate: () => void;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onRename: (id: number, title: string) => void;
  onToggleFlag: (conversation: AssistantConversationBrief, field: "pinned" | "favorite") => void;
}

export default function ConversationSidebar({
  conversations,
  loading,
  activeId,
  onCreate,
  onSelect,
  onDelete,
  onRename,
  onToggleFlag,
}: Props) {
  const [filter, setFilter] = useState<ConversationFilter>("all");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [actionMenuId, setActionMenuId] = useState<number | null>(null);
  const visibleConversations = (conversations ?? []).filter((conversation) =>
    filter === "favorite" ? conversation.favorite : true,
  );

  const startRename = (conversation: AssistantConversationBrief) => {
    setActionMenuId(null);
    setEditingId(conversation.id);
    setEditingTitle(conversation.title);
  };

  const saveTitle = (id: number) => {
    const title = editingTitle.trim();
    if (!title) return;
    onRename(id, title);
    setEditingId(null);
  };

  return (
    <aside className="assistant-sidebar">
      <Button type="primary" block icon={<PlusOutlined />} onClick={onCreate}>
        新对话
      </Button>
      <Segmented
        className="assistant-conversation-filter"
        block
        value={filter}
        options={[
          { label: "全部", value: "all" },
          { label: "收藏", value: "favorite" },
        ]}
        onChange={(value) => setFilter(value as ConversationFilter)}
      />
      <List
        className="assistant-conversation-list"
        loading={loading}
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
                      onClick={() => startRename(conversation)}
                    >
                      重命名
                    </Button>
                    <Button
                      type="text"
                      size="small"
                      icon={conversation.pinned ? <PushpinFilled /> : <PushpinOutlined />}
                      onClick={() => {
                        setActionMenuId(null);
                        onToggleFlag(conversation, "pinned");
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
                        onToggleFlag(conversation, "favorite");
                      }}
                    >
                      {conversation.favorite ? "取消收藏" : "收藏对话"}
                    </Button>
                    <Popconfirm
                      title="删除这段对话？"
                      onConfirm={() => {
                        setActionMenuId(null);
                        onDelete(conversation.id);
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
                    onClick={() => saveTitle(conversation.id)}
                  />
                }
                onChange={(event) => setEditingTitle(event.target.value)}
                onPressEnter={() => saveTitle(conversation.id)}
              />
            ) : (
              <ConversationTitle
                title={conversation.title}
                pinned={conversation.pinned}
                favorite={conversation.favorite}
                onSelect={() => onSelect(conversation.id)}
              />
            )}
          </List.Item>
        )}
      />
    </aside>
  );
}
