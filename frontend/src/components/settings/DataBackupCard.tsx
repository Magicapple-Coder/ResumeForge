/** 数据备份与恢复：导出全部本地数据，或从备份包恢复。 */

import { DownloadOutlined, UploadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Descriptions, Modal, Typography, Upload } from "antd";
import type { BackupPreview } from "../../types";
import { formatDateTime } from "../../utils/format";

interface Props {
  exporting: boolean;
  uploading: boolean;
  applying: boolean;
  preview: BackupPreview | null;
  onExport: () => void;
  onSelectFile: (file: File) => void;
  onConfirmRestore: () => void;
  onCancelRestore: () => void;
}

/** 只展示用户有直观感受的表，其余（附件、消息等）并入总量。 */
const TABLE_LABELS: Record<string, string> = {
  job: "岗位",
  user_profile: "个人资料",
  resume_record: "简历",
  chat_conversation: "助手会话",
  chat_message: "助手消息",
  llm_config_record: "模型配置记录",
};

function describeCounts(tables: Record<string, number>): string {
  const parts = Object.entries(TABLE_LABELS)
    .map(([key, label]) => [label, tables[key] ?? 0] as const)
    .filter(([, count]) => count > 0)
    .map(([label, count]) => `${label} ${count}`);
  return parts.length > 0 ? parts.join("、") : "没有可展示的数据";
}

/** 找出备份里比当前少的数据，恢复会让这部分永久丢失。 */
function describeShrink(preview: BackupPreview): string | null {
  const lost = Object.entries(TABLE_LABELS)
    .map(([key, label]) => {
      const current = preview.current_tables[key] ?? 0;
      const incoming = preview.database.tables[key] ?? 0;
      return { label, current, incoming };
    })
    .filter((item) => item.incoming < item.current);
  if (lost.length === 0) return null;
  return lost
    .map((item) => `${item.label}：当前 ${item.current} → 备份 ${item.incoming}`)
    .join("；");
}

export default function DataBackupCard({
  exporting,
  uploading,
  applying,
  preview,
  onExport,
  onSelectFile,
  onConfirmRestore,
  onCancelRestore,
}: Props) {
  const busy = exporting || uploading || applying;
  const shrink = preview ? describeShrink(preview) : null;

  return (
    <>
      <Card
        title="数据备份与恢复"
        className="settings-card"
        extra={
          <Button
            icon={<DownloadOutlined />}
            loading={exporting}
            disabled={busy}
            onClick={onExport}
          >
            导出全部数据
          </Button>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          岗位、个人资料、简历、收藏、求职助手会话和全部附件都保存在本机数据库里，导出的 zip
          就是完整的一份。为安全起见，备份中<strong>不包含大模型 API Key</strong>
          ，换电脑或恢复后需要重新填写。
        </Typography.Paragraph>
        <Upload
          accept=".zip,application/zip"
          showUploadList={false}
          disabled={busy}
          beforeUpload={(file) => {
            onSelectFile(file as File);
            // 与仓库其它上传一致：本地读取后自行提交，不走 antd 的上传通道。
            return Upload.LIST_IGNORE;
          }}
        >
          <Button icon={<UploadOutlined />} loading={uploading} disabled={exporting || applying}>
            导入备份…
          </Button>
        </Upload>
      </Card>

      <Modal
        title="确认恢复备份"
        open={preview !== null}
        okText="确认恢复"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        confirmLoading={applying}
        closable={!applying}
        maskClosable={!applying}
        // 关闭后立刻卸载，避免上一次的预览数据残留在 DOM 里。
        destroyOnHidden
        onOk={onConfirmRestore}
        onCancel={onCancelRestore}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="当前数据会被整体替换"
          description="备份中不含大模型 API Key，恢复后请到「大模型配置」重新填写并测试连接；其余设置、岗位、简历和会话都会还原成备份时的状态。"
        />
        {shrink && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="备份中的数据少于当前数据"
            description={`${shrink}。恢复后多出来的内容将无法找回。`}
          />
        )}
        {preview && (
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="导出时间">
              {formatDateTime(preview.manifest.exported_at)}
            </Descriptions.Item>
            <Descriptions.Item label="导出版本">{preview.manifest.app_version}</Descriptions.Item>
            <Descriptions.Item label="备份内容">
              {describeCounts(preview.database.tables)}
            </Descriptions.Item>
          </Descriptions>
        )}
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          message="恢复前会自动把当前数据库备份到 backend/data/backups/，需要回滚时可以从该目录取用。"
        />
      </Modal>
    </>
  );
}
