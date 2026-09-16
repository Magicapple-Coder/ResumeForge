/** 识别前的文件暂存区：截图显示缩略图，文档显示文件名。 */

import {
  DeleteOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  PictureOutlined,
} from "@ant-design/icons";
import { Button, Image, Tag, Tooltip, Typography, Upload } from "antd";
import type { StagedFile } from "../hooks/useRecognitionFiles";
import { MAX_ATTACHMENT_COUNT, RECOGNITION_ACCEPT, canPreviewImage } from "../utils/attachments";

interface Props {
  files: StagedFile[];
  reading: boolean;
  disabled?: boolean;
  onAddFiles: (files: File[]) => void;
  onRemove: (id: number) => void;
}

function documentIcon(name: string) {
  return name.toLowerCase().endsWith(".pdf") ? <FilePdfOutlined /> : <FileWordOutlined />;
}

export default function RecognitionFileField({
  files,
  reading,
  disabled = false,
  onAddFiles,
  onRemove,
}: Props) {
  const full = files.length >= MAX_ATTACHMENT_COUNT;
  const busy = reading || disabled;

  return (
    <div className="recognition-files">
      <div className="recognition-files-actions">
        <Upload
          accept={RECOGNITION_ACCEPT}
          multiple
          showUploadList={false}
          disabled={busy || full}
          // 页面上有多个上传入口，这个 aria-label 让它们（以及测试）都能精确定位。
          aria-label="添加截图或文档"
          beforeUpload={(file) => {
            onAddFiles([file as File]);
            // 与仓库其它上传一致：本地读取后自行提交，不走 antd 的上传通道。
            return Upload.LIST_IGNORE;
          }}
        >
          <Button icon={<PictureOutlined />} loading={reading} disabled={busy || full}>
            添加截图或文档
          </Button>
        </Upload>
        <Typography.Text type="secondary">
          也可以在文本框里按 Ctrl+V 粘贴截图（最多 {MAX_ATTACHMENT_COUNT} 个，单个 ≤ 2 MB，合计 ≤ 5
          MB；支持截图与 pdf/docx 文档）
        </Typography.Text>
      </div>

      {files.length > 0 && (
        <div className="recognition-files-list">
          {files.map((file) => (
            <div key={file.id} className="recognition-file-item">
              {file.kind === "image" && canPreviewImage(file.mime_type) ? (
                <Image src={file.data} alt={file.name} className="recognition-image" />
              ) : (
                // 浏览器渲染不了的图片（TIFF）和文档都用文件名标签，不做破图预览。
                <Tooltip title={file.name}>
                  <Tag
                    className="recognition-file-tag"
                    icon={file.kind === "image" ? <PictureOutlined /> : documentIcon(file.name)}
                  >
                    {file.name}
                  </Tag>
                </Tooltip>
              )}
              <Tooltip title={`移除 ${file.name}`}>
                <Button
                  type="text"
                  size="small"
                  danger
                  aria-label={`移除文件 ${file.name}`}
                  icon={<DeleteOutlined />}
                  disabled={busy}
                  onClick={() => onRemove(file.id)}
                />
              </Tooltip>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
