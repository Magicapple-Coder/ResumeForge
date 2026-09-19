/**
 * 「我的资料」页里的通用简历区块。
 *
 * 通用简历**不关联任何岗位**（`job_id` 为空），用于跨行业投递。它必须放在资料表单
 * 之外：写简历不是改资料，这个区块在非编辑状态下也要能用。
 */

import { DeleteOutlined, EditOutlined, FileSearchOutlined, PlusOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Card,
  Empty,
  Input,
  List,
  Popconfirm,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { deleteResume, listResumes, renameResume } from "../../api/resumes";
import type { ResumeBrief } from "../../types";
import { formatDateTime } from "../../utils/format";
import ResumeDetailModal from "../ResumeDetailModal";

const PAGE_SIZE = 50;

interface Props {
  /** 点「AI 生成」时把当前输入的名称带过去。 */
  onGenerate: (title: string) => void;
  /** 点「从头手写」时同上。 */
  onWrite: (title: string) => void;
}

export default function GeneralResumeSection({ onGenerate, onWrite }: Props) {
  const { message } = App.useApp();
  const [items, setItems] = useState<ResumeBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [previewId, setPreviewId] = useState<number | null>(null);
  /** 正在就地编辑名称的那一行（不是"正在保存"——两者混用会让保存被守卫挡掉）。 */
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [savingRename, setSavingRename] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const page = await listResumes({ has_job: false, page: 1, page_size: PAGE_SIZE });
      setItems(page.items);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "加载通用简历失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // 只在进入页面时加载一次；增删后由各操作自行刷新。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const confirmRename = async (record: ResumeBrief) => {
    if (savingRename) return;
    const nextTitle = renameValue.trim();
    if (!nextTitle) {
      message.warning("名称不能为空");
      return;
    }
    setSavingRename(true);
    try {
      await renameResume(record.id, nextTitle);
      setItems((current) =>
        current.map((item) => (item.id === record.id ? { ...item, title: nextTitle } : item)),
      );
      message.success("已重命名");
      setRenameValue("");
      setRenamingId(null);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重命名失败");
    } finally {
      setSavingRename(false);
    }
  };

  const remove = async (record: ResumeBrief) => {
    if (deletingId !== null) return;
    setDeletingId(record.id);
    try {
      await deleteResume(record.id);
      setItems((current) => current.filter((item) => item.id !== record.id));
      message.success(`已移入回收站：「${record.title}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <>
      <Card id="general-resume-section" title="通用简历" className="profile-general-resume">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          通用简历<strong>不针对任何岗位</strong>
          ，用来投给方向还不确定的机会。生成时会完整使用你的资料（各方向的经历、校园经历、项目、
          技能和奖项都保留，只受单份简历的篇幅限制），也可以从空白开始自己写。它们同时会出现在简历中心。
        </Typography.Paragraph>

        <Space wrap style={{ marginBottom: 8 }}>
          <Input
            aria-label="通用简历名称"
            value={title}
            maxLength={64}
            style={{ width: 260 }}
            placeholder="新简历名称（留空自动命名）"
            onChange={(event) => setTitle(event.target.value)}
          />
          <Button type="primary" icon={<FileSearchOutlined />} onClick={() => onGenerate(title)}>
            AI 生成
          </Button>
          <Button icon={<PlusOutlined />} onClick={() => onWrite(title)}>
            从头手写
          </Button>
        </Space>

        <List
          loading={loading}
          dataSource={items}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有通用简历" />,
          }}
          renderItem={(record) => (
            <List.Item
              actions={[
                <Tooltip key="rename" title="重命名">
                  <Button
                    type="text"
                    aria-label={`重命名通用简历 ${record.title}`}
                    icon={<EditOutlined />}
                    disabled={renamingId !== null || deletingId !== null}
                    onClick={() => {
                      setRenameValue(record.title);
                      setRenamingId(record.id);
                    }}
                  />
                </Tooltip>,
                <Popconfirm
                  key="delete"
                  title={`确定删除「${record.title}」？`}
                  description="删除后无法恢复，简历正文也会一起删除"
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => void remove(record)}
                >
                  <Tooltip title="删除">
                    <Button
                      type="text"
                      danger
                      aria-label={`删除通用简历 ${record.title}`}
                      icon={<DeleteOutlined />}
                      loading={deletingId === record.id}
                      disabled={renamingId !== null || deletingId !== null}
                    />
                  </Tooltip>
                </Popconfirm>,
              ]}
            >
              {renamingId === record.id ? (
                <Space.Compact style={{ width: "100%" }}>
                  <Input
                    aria-label="重命名输入框"
                    value={renameValue}
                    maxLength={64}
                    onChange={(event) => setRenameValue(event.target.value)}
                    onPressEnter={() => void confirmRename(record)}
                  />
                  <Button
                    type="primary"
                    loading={savingRename}
                    onClick={() => void confirmRename(record)}
                  >
                    保存
                  </Button>
                  <Button
                    onClick={() => {
                      setRenamingId(null);
                      setRenameValue("");
                    }}
                  >
                    取消
                  </Button>
                </Space.Compact>
              ) : (
                <List.Item.Meta
                  title={
                    <Button
                      type="link"
                      style={{ padding: 0 }}
                      onClick={() => setPreviewId(record.id)}
                    >
                      {record.title}
                    </Button>
                  }
                  description={
                    <>
                      <Tag color="purple">通用简历</Tag>
                      {record.job_title ? `求职意向：${record.job_title}` : "未填写求职意向"}
                      {record.created_at ? ` · ${formatDateTime(record.created_at)}` : ""}
                    </>
                  }
                />
              )}
            </List.Item>
          )}
        />
      </Card>

      <ResumeDetailModal
        recordId={previewId}
        onClose={() => {
          setPreviewId(null);
          void load();
        }}
      />
    </>
  );
}
