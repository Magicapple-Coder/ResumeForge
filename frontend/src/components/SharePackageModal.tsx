/** 离线分享包：选择分享版本 + 权限 + 脱敏范围 → 生成 → 展示本地路径 / 文件清单 / 评论导入。 */
import { CopyOutlined, DeleteOutlined, FolderOpenOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Checkbox,
  Descriptions,
  Modal,
  Popconfirm,
  Radio,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import {
  createSharePackage,
  deleteSharePackage,
  downloadSharePackageFile,
  getSharePackageComments,
  importSharePackageComments,
  revealSharePackage,
} from "../api/sharePackages";
import type { SharePackageDetail } from "../types";
import {
  DEFAULT_REDACTION_OPTIONS,
  REDACTION_FIELDS,
  type RedactionOptions,
} from "../types/export";
import { SHARE_PERMISSIONS, type SharePermission } from "../types/sharePackage";
import { copyText } from "../utils/clipboard";
import { downloadBlob } from "../utils/download";

interface Props {
  recordId: number;
  open: boolean;
  onClose: () => void;
}

/** 从文件清单的第一个文件路径反推分享包目录。 */
function deriveDirectory(detail: SharePackageDetail | null): string {
  const first = detail?.files?.[0]?.path;
  if (!first) return "";
  return first.replace(/[/\\][^/\\]*$/, "");
}

export default function SharePackageModal({ recordId, open, onClose }: Props) {
  const { message } = App.useApp();
  const [permission, setPermission] = useState<SharePermission>("read_only");
  const [redactOptions, setRedactOptions] = useState<RedactionOptions>(DEFAULT_REDACTION_OPTIONS);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<SharePackageDetail | null>(null);
  const [comments, setComments] = useState("");
  const [commentText, setCommentText] = useState("");
  const [commentFormat, setCommentFormat] = useState<"markdown" | "json">("markdown");
  const [importing, setImporting] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [revealing, setRevealing] = useState(false);

  const generate = async () => {
    if (generating) return;
    setGenerating(true);
    setResult(null);
    setComments("");
    try {
      const detail = await createSharePackage({
        resume_id: recordId,
        permission,
        redact_options: redactOptions,
      });
      setResult(detail);
      if (detail.permission === "comment") {
        try {
          setComments((await getSharePackageComments(detail.id)).content);
        } catch {
          // 评论文件读取失败不阻断主流程，导入时仍可再试。
        }
      }
      message.success("分享包已生成");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "生成分享包失败");
    } finally {
      setGenerating(false);
    }
  };

  const importComments = async () => {
    if (!result || importing) return;
    if (!commentText.trim()) {
      message.warning("请先粘贴或填写收件人回传的评论");
      return;
    }
    setImporting(true);
    try {
      const imported = await importSharePackageComments(result.id, {
        content: commentText,
        format: commentFormat,
      });
      setComments(imported.content);
      setCommentText("");
      message.success("评论已导入");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导入评论失败");
    } finally {
      setImporting(false);
    }
  };

  const downloadFile = async (detail: SharePackageDetail, filename: string) => {
    setDownloading(filename);
    try {
      const file = await downloadSharePackageFile(detail.id, filename);
      downloadBlob(file.blob, file.filename);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "下载文件失败");
    } finally {
      setDownloading(null);
    }
  };

  const removePackage = async () => {
    if (!result || deleting) return;
    setDeleting(true);
    try {
      await deleteSharePackage(result.id);
      message.success("分享包已移入回收站，可在「回收站」里恢复");
      setResult(null);
      setComments("");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除分享包失败");
    } finally {
      setDeleting(false);
    }
  };

  const openDirectory = async () => {
    if (!result || revealing) return;
    setRevealing(true);
    try {
      await revealSharePackage(result.id);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "打开文件夹失败");
    } finally {
      setRevealing(false);
    }
  };

  const copyDirectory = async () => {
    const dir = deriveDirectory(result);
    if (!dir) return;
    const ok = await copyText(dir);
    if (ok) message.success("已复制分享包路径");
    else message.warning(`复制失败，可以手动复制：${dir}`);
  };

  return (
    <Modal
      title="离线分享包"
      open={open}
      onCancel={onClose}
      footer={null}
      width="min(680px, 94vw)"
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <div>
          <Typography.Text strong>分享权限</Typography.Text>
          <Radio.Group
            style={{ marginTop: 8 }}
            value={permission}
            onChange={(event) => setPermission(event.target.value as SharePermission)}
          >
            {SHARE_PERMISSIONS.map((value) => (
              <Radio key={value} value={value}>
                {value === "read_only" ? "只读（不可回传评论）" : "可评论（附带评论回传文件）"}
              </Radio>
            ))}
          </Radio.Group>
        </div>

        <div>
          <Typography.Text strong>脱敏范围</Typography.Text>
          <div style={{ marginTop: 8 }}>
            {REDACTION_FIELDS.map((field) => (
              <Checkbox
                key={field.key}
                checked={redactOptions[field.key]}
                onChange={(event) =>
                  setRedactOptions((prev) => ({ ...prev, [field.key]: event.target.checked }))
                }
              >
                {field.label}
              </Checkbox>
            ))}
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            分享包始终基于脱敏后的内容生成，不含真实敏感信息。
          </Typography.Text>
        </div>

        <Button type="primary" loading={generating} onClick={() => void generate()}>
          生成分享包
        </Button>

        {result && (
          <>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="标题">{result.title}</Descriptions.Item>
              <Descriptions.Item label="本地目录">{deriveDirectory(result)}</Descriptions.Item>
              <Descriptions.Item label="分享码">{result.share_token}</Descriptions.Item>
              <Descriptions.Item label="权限">
                <Tag color={result.permission === "comment" ? "blue" : "default"}>
                  {result.permission === "comment" ? "可评论" : "只读"}
                </Tag>
              </Descriptions.Item>
            </Descriptions>

            <div>
              <Typography.Text strong>使用说明</Typography.Text>
              <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0", fontSize: 12 }}>
                把整个文件夹发给对方，对方用浏览器打开 resume.html 即可查看。
                {result.permission === "comment"
                  ? " 如需评论，让对方填写 comments.md 后回传给你，你在下方「导入评论」导入。"
                  : ""}
              </Typography.Paragraph>
            </div>

            <Space wrap>
              <Button
                icon={<FolderOpenOutlined />}
                loading={revealing}
                onClick={() => void openDirectory()}
              >
                打开所在文件夹
              </Button>
              <Button icon={<CopyOutlined />} onClick={() => void copyDirectory()}>
                复制路径
              </Button>
            </Space>

            <div>
              <Typography.Text strong>文件清单</Typography.Text>
              <Space direction="vertical" style={{ width: "100%", marginTop: 8 }} size={4}>
                {result.files.map((file) => (
                  <Space key={file.name} style={{ width: "100%" }} wrap>
                    <Button
                      type="link"
                      loading={downloading === file.name}
                      onClick={() => void downloadFile(result, file.name)}
                    >
                      {file.name}
                    </Button>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {file.format} · {file.size} B
                    </Typography.Text>
                  </Space>
                ))}
              </Space>
            </div>

            {result.permission === "comment" && (
              <div>
                <Typography.Text strong>评论回传</Typography.Text>
                <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                  把收件人回传的评论内容粘贴进来导入（Markdown 或 JSON）。
                </Typography.Paragraph>
                <Space direction="vertical" style={{ width: "100%" }} size="small">
                  <Radio.Group
                    value={commentFormat}
                    onChange={(event) => setCommentFormat(event.target.value)}
                  >
                    <Radio value="markdown">Markdown</Radio>
                    <Radio value="json">JSON</Radio>
                  </Radio.Group>
                  <Typography.Paragraph
                    style={{ whiteSpace: "pre-wrap", margin: 0 }}
                    type={comments ? undefined : "secondary"}
                  >
                    {comments || "（还没有评论）"}
                  </Typography.Paragraph>
                  <Space.Compact style={{ width: "100%" }}>
                    <textarea
                      aria-label="评论回传内容"
                      className="ant-input"
                      rows={4}
                      value={commentText}
                      placeholder="粘贴收件人回传的评论内容"
                      onChange={(event) => setCommentText(event.target.value)}
                    />
                    <Button
                      type="primary"
                      loading={importing}
                      onClick={() => void importComments()}
                    >
                      导入评论
                    </Button>
                  </Space.Compact>
                </Space>
              </div>
            )}

            <Popconfirm
              title="删除此分享包？"
              description="删除后可在回收站里找回，不会立刻彻底删除。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true, "aria-label": `确认删除分享包 ${result.title}` }}
              onConfirm={() => void removePackage()}
            >
              <Button danger icon={<DeleteOutlined />} loading={deleting}>
                删除此分享包
              </Button>
            </Popconfirm>
          </>
        )}

        {generating && (
          <div style={{ textAlign: "center" }}>
            <Spin />
          </div>
        )}
      </Space>
    </Modal>
  );
}
