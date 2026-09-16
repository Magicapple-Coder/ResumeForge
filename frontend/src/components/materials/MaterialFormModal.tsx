/** 资料箱条目编辑：标题、分类、正文、链接、附件与备注。 */

import { DeleteOutlined, FileTextOutlined, PictureOutlined, PlusOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Form,
  Image,
  Input,
  Modal,
  Select,
  Space,
  Typography,
  Upload,
} from "antd";
import { useEffect, useState } from "react";
import type { Material, MaterialFile, MaterialPayload } from "../../types";
import { MATERIAL_CATEGORIES } from "../../types";
import {
  IMAGE_MIME_BY_EXTENSION,
  MAX_ATTACHMENT_BYTES,
  canPreviewImage,
  readAsDataUrl,
} from "../../utils/attachments";

/** 与后端 MAX_MATERIAL_* 保持一致（服务端仍是权威校验）。 */
const MAX_FILES = 4;
const MAX_IMAGE_FILES = 2;
const MAX_TEXT_FILE_CHARS = 100_000;

const IMAGE_ACCEPT = Object.keys(IMAGE_MIME_BY_EXTENSION)
  .filter((extension) => ["png", "jpg", "jpeg", "webp", "gif", "bmp"].includes(extension))
  .map((extension) => `.${extension}`)
  .join(",");
const TEXT_FILE_ACCEPT = ".txt,.md,.json,.csv";

interface Props {
  open: boolean;
  /** 传入资料表示编辑，传 null 表示新建。 */
  material: Material | null;
  categories: string[];
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (payload: MaterialPayload) => void;
}

function filesFromMaterial(material: Material | null): MaterialFile[] {
  if (!material) return [];
  return material.files.map((item) => ({ ...item }));
}

export default function MaterialFormModal({
  open,
  material,
  categories,
  submitting,
  onCancel,
  onSubmit,
}: Props) {
  const { message } = App.useApp();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<string>("其他");
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [files, setFiles] = useState<MaterialFile[]>([]);

  useEffect(() => {
    if (!open) return;
    setTitle(material?.title ?? "");
    setCategory(material?.category || "其他");
    setContent(material?.content ?? "");
    setUrl(material?.url ?? "");
    setNote(material?.note ?? "");
    setFiles(filesFromMaterial(material));
  }, [material, open]);

  const options = Array.from(new Set([...categories, ...MATERIAL_CATEGORIES]));

  const addImage = async (file: File) => {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      message.error("单张图片不能超过 2 MB");
      return;
    }
    if (files.filter((item) => item.data_url).length >= MAX_IMAGE_FILES) {
      message.warning(`一份资料最多附加 ${MAX_IMAGE_FILES} 张图片`);
      return;
    }
    if (files.length >= MAX_FILES) {
      message.warning(`一份资料最多附加 ${MAX_FILES} 个文件`);
      return;
    }
    try {
      const dataUrl = await readAsDataUrl(file);
      setFiles((current) => [
        ...current,
        {
          name: file.name,
          mime_type: file.type || "image/*",
          size_bytes: file.size,
          text: "",
          data_url: dataUrl,
        },
      ]);
    } catch {
      message.error("读取图片失败，请重试");
    }
  };

  const addTextFile = async (file: File) => {
    if (files.length >= MAX_FILES) {
      message.warning(`一份资料最多附加 ${MAX_FILES} 个文件`);
      return;
    }
    try {
      const text = await file.text();
      if (!text.trim()) {
        message.warning("这个文件里没有可读的文字");
        return;
      }
      setFiles((current) => [
        ...current,
        {
          name: file.name,
          mime_type: file.type || "text/plain",
          size_bytes: file.size,
          text: text.slice(0, MAX_TEXT_FILE_CHARS),
          data_url: "",
        },
      ]);
    } catch {
      message.error("读取文件失败，请重试");
    }
  };

  const submit = () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle && !content.trim() && !url.trim() && files.length === 0) {
      message.warning("请至少填写标题、内容、链接或添加附件");
      return;
    }
    onSubmit({
      title: trimmedTitle,
      category: category.trim() || "其他",
      content,
      url: url.trim(),
      note,
      files,
    });
  };

  return (
    <Modal
      title={material ? `编辑资料：${material.title || material.category}` : "放入一条新资料"}
      open={open}
      width={720}
      onCancel={onCancel}
      maskClosable={!submitting}
      footer={
        <Space>
          <Button onClick={onCancel} disabled={submitting}>
            取消
          </Button>
          <Button type="primary" loading={submitting} onClick={submit}>
            保存
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="资料箱用来放还没整理进简历的零散材料：证书、作品说明、链接、笔记等。求职助手可以读取这里的内容并按需引用。"
      />
      <Form layout="vertical">
        <Form.Item label="标题">
          <Input
            value={title}
            maxLength={256}
            placeholder="如：CET-6 成绩单 / 个人作品集链接"
            onChange={(event) => setTitle(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="分类">
          <Select
            // tags 模式的取值是数组，这里始终只放一项，对外仍当单个字符串用。
            value={category ? [category] : []}
            showSearch
            options={options.map((item) => ({ value: item, label: item }))}
            // 允许输入新分类：资料类型很个人化，固定的那几个只能算起点。
            mode="tags"
            maxCount={1}
            onChange={(values: string[]) => setCategory(values[values.length - 1] ?? "其他")}
            placeholder="选择或输入一个新分类"
          />
        </Form.Item>
        <Form.Item label="正文内容">
          <Input.TextArea
            value={content}
            autoSize={{ minRows: 4, maxRows: 12 }}
            placeholder="粘贴资料原文，或写下要点说明"
            onChange={(event) => setContent(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="相关链接">
          <Input
            value={url}
            placeholder="https://…（选填）"
            onChange={(event) => setUrl(event.target.value)}
          />
        </Form.Item>
        <Form.Item label={`附件（最多 ${MAX_FILES} 个，其中图片最多 ${MAX_IMAGE_FILES} 张）`}>
          <Space wrap>
            <Upload
              accept={IMAGE_ACCEPT}
              showUploadList={false}
              beforeUpload={(file) => {
                void addImage(file as File);
                return Upload.LIST_IGNORE;
              }}
            >
              <Button icon={<PictureOutlined />}>添加图片</Button>
            </Upload>
            <Upload
              accept={TEXT_FILE_ACCEPT}
              showUploadList={false}
              beforeUpload={(file) => {
                void addTextFile(file as File);
                return Upload.LIST_IGNORE;
              }}
            >
              <Button icon={<FileTextOutlined />}>添加文本文件</Button>
            </Upload>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              PDF / Word 请把文字粘贴到正文，程序不保存原始文件
            </Typography.Text>
          </Space>
          {files.length > 0 && (
            <div className="material-file-list">
              {files.map((item, index) => (
                <div key={`${item.name}-${index}`} className="material-file-item">
                  {item.data_url && canPreviewImage(item.mime_type) ? (
                    <Image src={item.data_url} alt={item.name} width={64} />
                  ) : (
                    <PlusOutlined className="material-file-icon" />
                  )}
                  <div className="material-file-meta">
                    <Typography.Text ellipsis={{ tooltip: item.name }}>{item.name}</Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {item.data_url
                        ? `图片 · ${Math.round(item.size_bytes / 1024)} KB`
                        : `文字 ${item.text.length} 字`}
                    </Typography.Text>
                  </div>
                  <Button
                    type="text"
                    size="small"
                    danger
                    aria-label={`移除附件 ${item.name}`}
                    icon={<DeleteOutlined />}
                    onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                  />
                </div>
              ))}
            </div>
          )}
        </Form.Item>
        <Form.Item label="备注" style={{ marginBottom: 0 }}>
          <Input.TextArea
            value={note}
            autoSize={{ minRows: 2, maxRows: 5 }}
            placeholder="为什么留下它、还缺什么（选填）"
            onChange={(event) => setNote(event.target.value)}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
