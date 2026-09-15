/** 数据集管理：导入多份备份、在它们之间切换，以及导出/重命名/删除。 */

import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  SwapOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import type { DatasetInfo } from "../../types";
import { formatDateTime } from "../../utils/format";

interface Props {
  datasets: DatasetInfo[];
  loading: boolean;
  exporting: boolean;
  importing: boolean;
  switchingId: string | null;
  renamingId: string | null;
  deletingId: string | null;
  renameTarget: DatasetInfo | null;
  renameValue: string;
  onExport: (dataset: DatasetInfo) => void;
  onImport: (file: File, name: string) => void;
  onActivate: (dataset: DatasetInfo) => void;
  onOpenRename: (dataset: DatasetInfo) => void;
  onRenameValueChange: (value: string) => void;
  onConfirmRename: () => void;
  onCancelRename: () => void;
  onDelete: (dataset: DatasetInfo) => void;
}

function formatSize(bytes: number): string {
  if (bytes <= 0) return "—";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** 只有主数据不支持改名/删除，这里把规则收在一处，避免三处各写一遍。 */
function isProtected(dataset: DatasetInfo): boolean {
  return dataset.id === "main";
}

export default function DatasetsCard({
  datasets,
  loading,
  exporting,
  importing,
  switchingId,
  renamingId,
  deletingId,
  renameTarget,
  renameValue,
  onExport,
  onImport,
  onActivate,
  onOpenRename,
  onRenameValueChange,
  onConfirmRename,
  onCancelRename,
  onDelete,
}: Props) {
  const busy = exporting || importing || switchingId !== null || deletingId !== null;
  const active = datasets.find((item) => item.is_active);

  return (
    <>
      <Card
        title="数据集"
        className="settings-card"
        extra={
          <Button
            icon={<DownloadOutlined />}
            loading={exporting}
            disabled={busy || !active}
            onClick={() => active && onExport(active)}
          >
            导出当前数据集
          </Button>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          每份数据集就是一个完整的简历通数据库（岗位、个人资料、简历、收藏、助手会话和全部附件），
          可以随时切换，互不影响。导入备份包只会<strong>新增</strong>一份数据集，当前正在使用的
          数据不会被动到；导出的备份中不包含大模型 API Key。
        </Typography.Paragraph>

        <Upload
          accept=".zip,application/zip"
          showUploadList={false}
          disabled={busy}
          // 设置页上有多个上传入口，这个 aria-label 让它们（以及测试）都能精确定位。
          aria-label="选择备份文件"
          beforeUpload={(file) => {
            const name = (file.name || "").replace(/\.zip$/i, "") || "导入的数据集";
            onImport(file as File, name);
            // 与仓库其它上传一致：本地读取后自行提交，不走 antd 的上传通道。
            return Upload.LIST_IGNORE;
          }}
        >
          <Button icon={<UploadOutlined />} loading={importing} disabled={busy}>
            导入备份为新数据集
          </Button>
        </Upload>

        <List
          style={{ marginTop: 16 }}
          loading={loading}
          dataSource={datasets}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据集" />,
          }}
          renderItem={(dataset) => (
            <List.Item
              actions={[
                <Tooltip key="switch" title={dataset.is_active ? "正在使用" : "切换到这份数据"}>
                  <Button
                    type="link"
                    icon={<SwapOutlined />}
                    disabled={dataset.is_active || busy || !dataset.exists}
                    loading={switchingId === dataset.id}
                    onClick={() => onActivate(dataset)}
                  >
                    切换
                  </Button>
                </Tooltip>,
                <Tooltip
                  key="rename"
                  title={isProtected(dataset) ? "主数据不支持重命名" : "重命名"}
                >
                  <Button
                    type="text"
                    aria-label={`重命名 ${dataset.name}`}
                    icon={<EditOutlined />}
                    disabled={isProtected(dataset) || busy}
                    onClick={() => onOpenRename(dataset)}
                  />
                </Tooltip>,
                <Popconfirm
                  key="delete"
                  title={`确定删除数据集“${dataset.name}”？`}
                  description="会移入 data/datasets/.trash/，需要时可以手动找回"
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  disabled={dataset.is_active || busy || isProtected(dataset)}
                  onConfirm={() => onDelete(dataset)}
                >
                  <Tooltip title={dataset.is_active ? "不能删除正在使用的数据集" : "删除"}>
                    <Button
                      type="text"
                      danger
                      aria-label={`删除数据集 ${dataset.name}`}
                      icon={<DeleteOutlined />}
                      loading={deletingId === dataset.id}
                      disabled={dataset.is_active || busy || isProtected(dataset)}
                    />
                  </Tooltip>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <>
                    {dataset.name}
                    {dataset.is_active && (
                      <Tag color="blue" style={{ marginLeft: 8 }}>
                        当前
                      </Tag>
                    )}
                  </>
                }
                description={
                  <>
                    {formatSize(dataset.size_bytes)}
                    {dataset.created_at ? ` · ${formatDateTime(dataset.created_at)}` : ""}
                    {dataset.source ? ` · ${dataset.source}` : ""}
                  </>
                }
              />
            </List.Item>
          )}
        />
      </Card>

      <Modal
        title="重命名数据集"
        open={renameTarget !== null}
        okText="保存"
        cancelText="取消"
        confirmLoading={renamingId !== null}
        destroyOnHidden
        onOk={onConfirmRename}
        onCancel={onCancelRename}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="名称只用于在列表里区分，不影响数据内容。"
        />
        <Input
          value={renameValue}
          maxLength={64}
          onChange={(event) => onRenameValueChange(event.target.value)}
        />
      </Modal>
    </>
  );
}
