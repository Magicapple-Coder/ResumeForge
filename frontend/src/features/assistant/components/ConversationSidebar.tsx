/** 求职助手会话列表：筛选、按需管理操作与整行右键菜单。 */

import {
  DeleteOutlined,
  EditOutlined,
  FolderOutlined,
  InboxOutlined,
  LinkOutlined,
  MoreOutlined,
  PlusOutlined,
  PushpinFilled,
  PushpinOutlined,
  SaveOutlined,
  StarFilled,
  StarOutlined,
  SplitCellsOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Empty,
  Input,
  List,
  Popconfirm,
  Popover,
  Segmented,
  Tooltip,
  Typography,
} from "antd";
import { useState } from "react";
import type { AssistantConversationBrief, ConversationFilter } from "../../../types";
import { copyText } from "../../../utils/clipboard";
import { formatDateTime } from "../../../utils/format";
import { RowContextMenu, type RowActionItem } from "../../../components/common/RowActions";
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
  onArchive: (conversation: AssistantConversationBrief, archived: boolean) => void;
  onFork: (conversation: AssistantConversationBrief) => void;
  onMoveToGroup: (conversation: AssistantConversationBrief) => void;
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
  onArchive,
  onFork,
  onMoveToGroup,
}: Props) {
  const { message } = App.useApp();
  const [filter, setFilter] = useState<ConversationFilter>("all");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [actionMenuId, setActionMenuId] = useState<number | null>(null);

  const visibleConversations = (conversations ?? []).filter((conversation) => {
    if (filter === "archived") return conversation.archived;
    if (filter === "favorite") return conversation.favorite;
    return !conversation.archived;
  });

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

  const copyShareLink = async (conversation: AssistantConversationBrief) => {
    setActionMenuId(null);
    const link = `${window.location.origin}/assistant?conversation=${conversation.id}`;
    const ok = await copyText(link);
    if (ok) {
      message.success("已复制会话链接，在本应用打开即可回到这段对话");
    } else {
      message.warning(`复制失败，可以手动复制：${link}`);
    }
  };

  const copyConversationId = async (conversation: AssistantConversationBrief) => {
    setActionMenuId(null);
    const ok = await copyText(String(conversation.id));
    if (ok) message.success(`已复制会话 ID：${conversation.id}`);
  };

  /** 会话的完整操作清单：三点菜单与整行右键共用同一份。 */
  const actionsFor = (conversation: AssistantConversationBrief): RowActionItem[] => [
    {
      key: "pin",
      label: conversation.pinned ? "取消置顶" : "置顶对话",
      icon: conversation.pinned ? <PushpinFilled /> : <PushpinOutlined />,
      onClick: () => {
        setActionMenuId(null);
        onToggleFlag(conversation, "pinned");
      },
    },
    {
      key: "favorite",
      label: conversation.favorite ? "取消收藏" : "收藏对话",
      icon: conversation.favorite ? <StarFilled /> : <StarOutlined />,
      onClick: () => {
        setActionMenuId(null);
        onToggleFlag(conversation, "favorite");
      },
    },
    {
      key: "link",
      label: "复制分享链接",
      icon: <LinkOutlined />,
      onClick: () => void copyShareLink(conversation),
    },
    {
      key: "rename",
      label: "重命名",
      icon: <EditOutlined />,
      onClick: () => startRename(conversation),
    },
    {
      key: "fork",
      label: "在新对话中继续",
      icon: <SplitCellsOutlined />,
      onClick: () => {
        setActionMenuId(null);
        onFork(conversation);
      },
    },
    {
      key: "group",
      label: conversation.group_name
        ? `移动到分组（当前：${conversation.group_name}）`
        : "移动到分组",
      icon: <FolderOutlined />,
      onClick: () => {
        setActionMenuId(null);
        onMoveToGroup(conversation);
      },
    },
    {
      key: "copy-id",
      label: "复制会话 ID",
      icon: <LinkOutlined />,
      onClick: () => void copyConversationId(conversation),
    },
    {
      key: "archive",
      label: conversation.archived ? "取消归档" : "归档对话",
      icon: <InboxOutlined />,
      onClick: () => {
        setActionMenuId(null);
        onArchive(conversation, !conversation.archived);
      },
    },
    {
      key: "delete",
      label: "删除",
      danger: true,
      icon: <DeleteOutlined />,
      confirm: "删除这段对话？",
      onClick: () => {
        setActionMenuId(null);
        onDelete(conversation.id);
      },
    },
  ];

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
          { label: "已归档", value: "archived" },
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
          <RowContextMenu items={actionsFor(conversation)}>
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
                      {actionsFor(conversation).map((item) =>
                        item.confirm ? (
                          <Popconfirm
                            key={item.key}
                            title={item.confirm}
                            onConfirm={() => {
                              setActionMenuId(null);
                              item.onClick?.();
                            }}
                          >
                            <Button type="text" size="small" danger={item.danger} icon={item.icon}>
                              {item.label}
                            </Button>
                          </Popconfirm>
                        ) : (
                          <Button
                            key={item.key}
                            type="text"
                            size="small"
                            danger={item.danger}
                            icon={item.icon}
                            onClick={item.onClick}
                          >
                            {item.label}
                          </Button>
                        ),
                      )}
                    </div>
                  }
                >
                  <Tooltip title="更多操作（也可以直接右键这条对话）">
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
                    <Tooltip title="保存标题（回车也可以）">
                      <Button
                        type="text"
                        size="small"
                        aria-label="保存对话标题"
                        icon={<SaveOutlined />}
                        onClick={() => saveTitle(conversation.id)}
                      />
                    </Tooltip>
                  }
                  onChange={(event) => setEditingTitle(event.target.value)}
                  onPressEnter={() => saveTitle(conversation.id)}
                />
              ) : (
                <div className="assistant-conversation-item">
                  <ConversationTitle
                    title={conversation.title}
                    pinned={conversation.pinned}
                    favorite={conversation.favorite}
                    onSelect={() => onSelect(conversation.id)}
                  />
                  <Typography.Text type="secondary" className="assistant-conversation-meta">
                    {conversation.group_name ? `${conversation.group_name} · ` : ""}
                    {conversation.message_count} 条 · {formatDateTime(conversation.updated_at)}
                  </Typography.Text>
                </div>
              )}
            </List.Item>
          </RowContextMenu>
        )}
      />
    </aside>
  );
}
