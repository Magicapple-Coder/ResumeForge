/**
 * 「导入目标模板」：把一份别人给的简历（图片 / PDF / DOCX）变成一份可套用的格式模板。
 *
 * 为什么需要它：用户手里常有"我就想要这种样子"的简历，但让他照着图片手调行高、页边距、
 * 强调色是不现实的。这里把文件交给模型看一眼，直接产出那几项版式参数。
 *
 * 两个如实说明：
 * 1. **图片会发给模型**（它没有可本地抽取的结构化文字），文档则在本地抽文字后再分析；
 * 2. 产出的是一份**格式模板**（只调版式，不换 HTML），导入后在「简历中心 → 样式模板」
 *    里就能选到它。
 */
import { InboxOutlined } from "@ant-design/icons";
import { App, Alert, Form, Input, Modal, Typography, Upload } from "antd";
import type { UploadFile } from "antd";
import { useState } from "react";
import { importTemplateFromFile } from "../../api/resumeTemplates";
import type { ResumeTemplateDetail } from "../../types";

interface Props {
  open: boolean;
  onClose: () => void;
  /** 导入成功：父组件刷新列表。 */
  onImported: (template: ResumeTemplateDetail) => void;
}

/** 与后端一致：图片与文档各取所需，其余类型在服务端会被拒。 */
const ACCEPT = ".png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,.pdf,.docx";
/** 后端上限 2MB（`MAX_ATTACHMENT_BYTES`），这里提前拦一次，省得用户等一次失败。 */
const MAX_BYTES = 2 * 1024 * 1024;

export default function TemplateImportModal({ open, onClose, onImported }: Props) {
  const { message } = App.useApp();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [name, setName] = useState("");
  const [running, setRunning] = useState(false);

  const reset = () => {
    setFileList([]);
    setName("");
    setRunning(false);
  };

  const submit = async () => {
    const raw = fileList[0]?.originFileObj as File | undefined;
    if (!raw) {
      message.warning("先选一份目标模板文件");
      return;
    }
    setRunning(true);
    try {
      const created = await importTemplateFromFile(raw, name);
      message.success(`已导入格式模板「${created.name}」，在简历中心选模板时就能看到它`);
      onImported(created);
      reset();
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "导入失败，请稍后重试");
    } finally {
      setRunning(false);
    }
  };

  return (
    <Modal
      title="导入目标模板"
      open={open}
      onCancel={() => {
        if (running) return;
        reset();
        onClose();
      }}
      okText="开始识别"
      cancelText="取消"
      confirmLoading={running}
      okButtonProps={{ disabled: fileList.length === 0 }}
      onOk={() => void submit()}
      width={620}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        上传你想照着做的那份简历（<strong>图片</strong>或 <strong>PDF / DOCX</strong>），
        模型会读出它的强调色、行高、页边距等版式参数，生成一份可套用的格式模板。
      </Typography.Paragraph>
      <Upload.Dragger
        accept={ACCEPT}
        maxCount={1}
        fileList={fileList}
        // 不做自动上传：识别是一次显式的长操作（要走模型），由下面的按钮发起。
        beforeUpload={(file) => {
          if (file.size > MAX_BYTES) {
            message.error(`文件不能超过 ${MAX_BYTES / (1024 * 1024)} MB，请压缩后再试`);
            return Upload.LIST_IGNORE;
          }
          setFileList([
            {
              uid: file.uid,
              name: file.name,
              status: "done",
              originFileObj: file as UploadFile["originFileObj"],
            },
          ]);
          return false;
        }}
        onRemove={() => setFileList([])}
        style={{ marginBottom: 16 }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点这里选择，或把文件拖进来</p>
        <p className="ant-upload-hint">
          支持 PNG / JPG / WEBP 图片与 PDF / DOCX 文档，单个文件 ≤ 2 MB
        </p>
      </Upload.Dragger>

      <Form layout="vertical">
        <Form.Item label="模板名称（可留空，由模型起名）">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={40}
            placeholder="例如：深蓝简洁版式"
            aria-label="模板名称"
          />
        </Form.Item>
      </Form>

      <Alert
        type="info"
        showIcon
        message="识别需要已配置的大模型"
        description="图片会作为图片发给模型；PDF / DOCX 先在本地抽出文字再分析（原始文件不外发）。识别结果是一份格式模板，随时可以删掉或再手动微调。"
      />
    </Modal>
  );
}
