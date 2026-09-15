/** 已保存的大模型配置记录及切换/删除操作。 */

import { DeleteOutlined, SaveOutlined, SwapOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { LLMConfigRecord } from "../../types";
import { formatDateTime } from "../../utils/format";
import { CUSTOM_PRESET_LABEL, matchingPreset } from "./SettingsConfig";

interface Props {
  records: LLMConfigRecord[];
  recordsLoading: boolean;
  activeRecordId: number | null;
  editing: boolean;
  saving: boolean;
  testing: boolean;
  recordSaving: boolean;
  recordApplyingId: number | null;
  recordDeletingId: number | null;
  recordModalOpen: boolean;
  recordName: string;
  onOpenRecordModal: () => void;
  onApplyRecord: (record: LLMConfigRecord) => void;
  onRemoveRecord: (record: LLMConfigRecord) => void;
  onRecordNameChange: (value: string) => void;
  onSaveRecord: () => void;
  onCloseRecordModal: () => void;
}

export default function LLMConfigRecordsCard({
  records,
  recordsLoading,
  activeRecordId,
  editing,
  saving,
  testing,
  recordSaving,
  recordApplyingId,
  recordDeletingId,
  recordModalOpen,
  recordName,
  onOpenRecordModal,
  onApplyRecord,
  onRemoveRecord,
  onRecordNameChange,
  onSaveRecord,
  onCloseRecordModal,
}: Props) {
  return (
    <>
      <Card
        title="配置记录"
        className="settings-card"
        extra={
          <Button
            icon={<SaveOutlined />}
            disabled={
              editing ||
              saving ||
              testing ||
              recordSaving ||
              recordApplyingId !== null ||
              recordsLoading
            }
            onClick={onOpenRecordModal}
          >
            保存当前配置
          </Button>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          将当前已保存的配置命名后加入记录；切换记录会直接更新当前使用的配置。
        </Typography.Paragraph>
        <List
          itemLayout="horizontal"
          loading={recordsLoading}
          dataSource={records}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无配置记录" />,
          }}
          renderItem={(record) => (
            <List.Item
              actions={[
                <Button
                  key="apply"
                  type="link"
                  icon={<SwapOutlined />}
                  disabled={
                    editing ||
                    saving ||
                    testing ||
                    recordApplyingId !== null ||
                    recordDeletingId !== null
                  }
                  loading={recordApplyingId === record.id}
                  onClick={() => onApplyRecord(record)}
                >
                  使用
                </Button>,
                <Popconfirm
                  key="delete"
                  title={`确定删除配置记录“${record.name}”？`}
                  description="删除记录不会影响当前正在使用的配置"
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  disabled={editing || recordApplyingId !== null || recordDeletingId !== null}
                  onConfirm={() => onRemoveRecord(record)}
                >
                  <Tooltip title="删除记录">
                    <Button
                      type="text"
                      danger
                      aria-label={`删除配置记录 ${record.name}`}
                      icon={<DeleteOutlined />}
                      loading={recordDeletingId === record.id}
                    />
                  </Tooltip>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={8} wrap>
                    <Typography.Text strong>{record.name}</Typography.Text>
                    {activeRecordId === record.id && <Tag color="green">当前</Tag>}
                  </Space>
                }
                description={
                  <Space size={[8, 4]} wrap>
                    <Tag>{matchingPreset(record)?.label ?? CUSTOM_PRESET_LABEL}</Tag>
                    <Typography.Text type="secondary">
                      {record.model || "未填写模型"}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      温度 {record.temperature.toFixed(1)}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {record.base_url || "未填写地址"}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      更新于 {formatDateTime(record.updated_at)}
                    </Typography.Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      </Card>

      <Modal
        title="保存为配置记录"
        open={recordModalOpen}
        confirmLoading={recordSaving}
        okText="保存记录"
        cancelText="取消"
        onOk={onSaveRecord}
        onCancel={onCloseRecordModal}
      >
        <Form layout="vertical">
          <Form.Item label="记录名称" required style={{ marginBottom: 8 }}>
            <Input
              autoFocus
              maxLength={64}
              showCount
              value={recordName}
              placeholder="如：DeepSeek 校招、Ollama 本地模型"
              onChange={(event) => onRecordNameChange(event.target.value)}
              onPressEnter={onSaveRecord}
            />
          </Form.Item>
          <Typography.Text type="secondary">
            只保存当前已保存的配置，不会保存未点击“保存配置”的编辑内容。
          </Typography.Text>
        </Form>
      </Modal>
    </>
  );
}
