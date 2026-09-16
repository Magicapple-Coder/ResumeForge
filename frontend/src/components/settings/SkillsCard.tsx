/** 助手技能管理：导入、点击查看详情、启用/停用与删除。 */

import { DeleteOutlined, UploadOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Empty,
  List,
  Popconfirm,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import type { AssistantSkill } from "../../types";
import { formatDateTime } from "../../utils/format";

interface Props {
  skills: AssistantSkill[];
  loading: boolean;
  importing: boolean;
  togglingId: number | null;
  deletingId: number | null;
  onImport: (file: File) => void;
  onToggle: (skill: AssistantSkill, enabled: boolean) => void;
  onDelete: (skill: AssistantSkill) => void;
  /** 点击技能名查看详情（提示词全文与知识文件）。 */
  onOpen: (skill: AssistantSkill) => void;
}

function describe(skill: AssistantSkill): string {
  const files = skill.files.length > 0 ? `${skill.files.length} 份知识文件` : "仅提示词";
  return [
    skill.description || "未填写适用场景",
    files,
    `提示词 ${skill.prompt_chars} 字`,
    `更新于 ${formatDateTime(skill.updated_at)}`,
  ].join(" · ");
}

export default function SkillsCard({
  skills,
  loading,
  importing,
  togglingId,
  deletingId,
  onImport,
  onToggle,
  onDelete,
  onOpen,
}: Props) {
  // 同一时刻只允许一个改动在进行，避免连点产生互相覆盖的请求。
  const busy = importing || deletingId !== null;

  return (
    <Card title="助手技能" className="settings-card">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        技能是一份<strong>提示词</strong>，也可以再带上一包<strong>知识文件</strong>
        （.md / .txt）。启用的技能会告诉助手「按什么要求作答」，知识文件则由助手在需要时自己去读，
        不会一次性塞进对话。导入同名技能会覆盖更新，方便反复调整。 想新建或改得更细可以到
        <strong>技能工作台</strong>。
      </Typography.Paragraph>

      <Upload
        accept=".md,.zip"
        showUploadList={false}
        disabled={busy}
        // 设置页上有多个上传入口，这个 aria-label 让它们（以及测试）都能精确定位。
        aria-label="选择技能文件"
        beforeUpload={(file) => {
          onImport(file as File);
          // 与仓库其它上传一致：本地读取后自行提交，不走 antd 的上传通道。
          return Upload.LIST_IGNORE;
        }}
      >
        <Button icon={<UploadOutlined />} loading={importing} disabled={busy}>
          导入技能（.md 或 .zip）
        </Button>
      </Upload>

      <List
        style={{ marginTop: 16 }}
        loading={loading}
        dataSource={skills}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有导入技能" />,
        }}
        renderItem={(skill) => (
          <List.Item
            actions={[
              <Tooltip
                key="toggle"
                title={skill.enabled ? "停用后助手不再使用它" : "启用后助手会照它作答"}
              >
                <Switch
                  size="small"
                  checked={skill.enabled}
                  aria-label={`${skill.enabled ? "停用" : "启用"}技能 ${skill.name}`}
                  loading={togglingId === skill.id}
                  disabled={busy || (togglingId !== null && togglingId !== skill.id)}
                  onChange={(checked) => onToggle(skill, checked)}
                />
              </Tooltip>,
              <Popconfirm
                key="delete"
                title={`确定删除技能“${skill.name}”？`}
                description="提示词和它附带的知识文件都会被删除，需要时可以重新导入"
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
                disabled={busy}
                onConfirm={() => onDelete(skill)}
              >
                <Tooltip title="删除（提示词与知识文件一起删除）">
                  <Button
                    type="text"
                    danger
                    aria-label={`删除技能 ${skill.name}`}
                    icon={<DeleteOutlined />}
                    loading={deletingId === skill.id}
                    disabled={busy}
                  />
                </Tooltip>
              </Popconfirm>,
            ]}
          >
            <List.Item.Meta
              title={
                <Space size={8} wrap>
                  {/* 技能名可点击：查看提示词全文与知识文件，也能就地改。 */}
                  <Button type="link" className="table-text-link" onClick={() => onOpen(skill)}>
                    {skill.name}
                  </Button>
                  <Tag color={skill.enabled ? "blue" : "default"}>
                    {skill.enabled ? "启用中" : "已停用"}
                  </Tag>
                </Space>
              }
              description={describe(skill)}
            />
          </List.Item>
        )}
      />
    </Card>
  );
}
