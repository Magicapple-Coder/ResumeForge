/** 粘贴整段个人资料（或资料截图）并结构化识别的弹窗。 */

import { FileSearchOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Modal, Typography } from "antd";
import type { StagedImage } from "../../hooks/useImageStaging";
import ImageStagingField from "../ImageStagingField";
import RecognizedTextField from "../RecognizedTextField";

interface Props {
  open: boolean;
  text: string;
  warnings: string[];
  parsing: boolean;
  recognizedText: string;
  images: StagedImage[];
  imagesReading: boolean;
  onTextChange: (value: string) => void;
  onAddImages: (files: File[]) => void;
  onRemoveImage: (id: number) => void;
  onPasteImages: (event: React.ClipboardEvent<HTMLElement>) => void;
  onClose: () => void;
  onParse: () => void;
}

export default function ProfileTextModal({
  open,
  text,
  warnings,
  parsing,
  recognizedText,
  images,
  imagesReading,
  onTextChange,
  onAddImages,
  onRemoveImage,
  onPasteImages,
  onClose,
  onParse,
}: Props) {
  return (
    <Modal
      title="粘贴个人资料并识别"
      open={open}
      onCancel={onClose}
      destroyOnHidden
      width={760}
      footer={[
        <Button key="cancel" onClick={onClose} disabled={parsing}>
          关闭
        </Button>,
        <Button
          key="parse"
          type="primary"
          icon={<FileSearchOutlined />}
          loading={parsing}
          onClick={onParse}
        >
          识别并填入
        </Button>,
      ]}
      styles={{ body: { paddingRight: 8 } }}
    >
      <Typography.Paragraph type="secondary">
        可粘贴包含基本信息、教育经历、实习/工作经历、校园经历、项目经历、技能和获奖情况的整段文字，
        也可以直接贴上这些内容的截图（在下面的输入框里按
        Ctrl+V）。若已配置大模型，内容会发送到该模型进行
        结构化识别；结果会直接回填当前编辑表单，请核对后再保存。识别图片需要支持图片输入的多模态模型。
      </Typography.Paragraph>
      <Input.TextArea
        aria-label="个人资料文本"
        value={text}
        disabled={parsing}
        onPaste={onPasteImages}
        onChange={(event) => onTextChange(event.target.value)}
        maxLength={100_000}
        showCount
        placeholder={
          "例如：\n姓名：张三\n教育经历\n天津工业大学｜软件工程｜本科｜2022.09-2026.06\n项目经历\n简历通｜核心开发｜Python、FastAPI"
        }
        autoSize={{ minRows: 14, maxRows: 24 }}
      />
      <ImageStagingField
        images={images}
        reading={imagesReading}
        disabled={parsing}
        onAddFiles={onAddImages}
        onRemove={onRemoveImage}
      />
      <RecognizedTextField text={recognizedText} />
      {warnings.length > 0 && (
        <Alert type="warning" showIcon style={{ marginTop: 12 }} message={warnings.join("；")} />
      )}
    </Modal>
  );
}
