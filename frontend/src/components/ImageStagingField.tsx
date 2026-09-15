/** 识别前的图片暂存区：选择文件、查看缩略图、逐张移除。 */

import { DeleteOutlined, PictureOutlined } from "@ant-design/icons";
import { Button, Image, Tooltip, Typography, Upload } from "antd";
import type { StagedImage } from "../hooks/useImageStaging";
import { IMAGE_ACCEPT, MAX_ATTACHMENT_COUNT } from "../utils/attachments";

interface Props {
  images: StagedImage[];
  reading: boolean;
  disabled?: boolean;
  onAddFiles: (files: File[]) => void;
  onRemove: (id: number) => void;
}

export default function ImageStagingField({
  images,
  reading,
  disabled = false,
  onAddFiles,
  onRemove,
}: Props) {
  const full = images.length >= MAX_ATTACHMENT_COUNT;
  const busy = reading || disabled;

  return (
    <div className="recognition-images">
      <div className="recognition-images-actions">
        <Upload
          accept={IMAGE_ACCEPT}
          multiple
          showUploadList={false}
          disabled={busy || full}
          // 页面上有多个上传入口，这个 aria-label 让它们（以及测试）都能精确定位。
          aria-label="添加截图"
          beforeUpload={(file) => {
            onAddFiles([file as File]);
            // 与仓库其它上传一致：本地读取后自行提交，不走 antd 的上传通道。
            return Upload.LIST_IGNORE;
          }}
        >
          <Button icon={<PictureOutlined />} loading={reading} disabled={busy || full}>
            添加截图
          </Button>
        </Upload>
        <Typography.Text type="secondary">
          也可以在文本框里按 Ctrl+V 粘贴截图（最多 {MAX_ATTACHMENT_COUNT} 张，单张 ≤ 2 MB，合计 ≤ 5
          MB）
        </Typography.Text>
      </div>

      {images.length > 0 && (
        <div className="recognition-images-list">
          {images.map((image) => (
            <div key={image.id} className="recognition-image-item">
              <Image src={image.data} alt={image.name} className="recognition-image" />
              <Tooltip title={`移除 ${image.name}`}>
                <Button
                  type="text"
                  size="small"
                  danger
                  aria-label={`移除截图 ${image.name}`}
                  icon={<DeleteOutlined />}
                  disabled={busy}
                  onClick={() => onRemove(image.id)}
                />
              </Tooltip>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
