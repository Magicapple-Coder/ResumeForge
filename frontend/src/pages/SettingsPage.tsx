/** 设置页：大模型配置（含预设与连通测试）。 */
import {
  ApiOutlined,
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  SaveOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Row,
  Select,
  Slider,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import {
  deleteLLMConfigRecord,
  getLLMConfig,
  listLLMConfigRecords,
  saveLLMConfig,
  saveLLMConfigRecord,
  testLLM,
} from "../api/settings";
import { LLM_PRESETS } from "../config";
import type { LLMConfig, LLMConfigRecord, LLMTestResult } from "../types";
import { formatDateTime } from "../utils/format";

const CUSTOM_PRESET = "custom";
const CUSTOM_PRESET_LABEL = "自定义模型（OpenAI 兼容）";
const PRESET_OPTIONS = [
  ...LLM_PRESETS.map((preset) => ({ value: preset.provider, label: preset.label })),
  { value: CUSTOM_PRESET, label: CUSTOM_PRESET_LABEL },
];

/** provider 由预设选择推导，避免未注册的隐藏字段在表单校验时丢失。 */
type SettingsFormValues = Omit<LLMConfig, "provider"> & { preset: string };

function formValuesFromConfig(config: LLMConfig): SettingsFormValues {
  const matched = LLM_PRESETS.find(
    (preset) => preset.provider === config.provider && preset.base_url === config.base_url,
  );
  return {
    base_url: config.base_url,
    api_key: config.api_key,
    model: config.model,
    temperature: config.temperature,
    timeout_seconds: config.timeout_seconds,
    max_tokens: config.max_tokens,
    preset: matched?.provider ?? CUSTOM_PRESET,
  };
}

function configFromFormValues(values: SettingsFormValues): LLMConfig {
  const preset = LLM_PRESETS.find((item) => item.provider === values.preset);
  return {
    provider: preset?.provider ?? CUSTOM_PRESET,
    base_url: values.base_url,
    api_key: values.api_key,
    model: values.model,
    temperature: values.temperature,
    timeout_seconds: values.timeout_seconds,
    max_tokens: values.max_tokens,
  };
}

function configFromRecord(record: LLMConfigRecord): LLMConfig {
  return {
    provider: record.provider,
    base_url: record.base_url,
    api_key: record.api_key,
    model: record.model,
    temperature: record.temperature,
    timeout_seconds: record.timeout_seconds,
    max_tokens: record.max_tokens,
  };
}

function sameConfig(left: LLMConfig, right: LLMConfig): boolean {
  return (
    left.provider === right.provider &&
    left.base_url === right.base_url &&
    left.api_key === right.api_key &&
    left.model === right.model &&
    left.temperature === right.temperature &&
    left.timeout_seconds === right.timeout_seconds &&
    left.max_tokens === right.max_tokens
  );
}

export default function SettingsPage() {
  const [form] = Form.useForm<SettingsFormValues>();
  const { message } = App.useApp();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [testResult, setTestResult] = useState<LLMTestResult | null>(null);
  const savedValues = useRef<SettingsFormValues | null>(null);
  const [records, setRecords] = useState<LLMConfigRecord[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [activeRecordId, setActiveRecordId] = useState<number | null>(null);
  const [recordModalOpen, setRecordModalOpen] = useState(false);
  const [recordName, setRecordName] = useState("");
  const [recordSaving, setRecordSaving] = useState(false);
  const [recordApplyingId, setRecordApplyingId] = useState<number | null>(null);
  const [recordDeletingId, setRecordDeletingId] = useState<number | null>(null);

  // 同时加载当前配置与记录，避免页面先显示一套配置、稍后又跳变到另一套状态。
  useEffect(() => {
    setRecordsLoading(true);
    void Promise.all([getLLMConfig(), listLLMConfigRecords()])
      .then(([config, loadedRecords]) => {
        const values = formValuesFromConfig(config);
        form.setFieldsValue(values);
        savedValues.current = values;
        setRecords(loadedRecords);
        setActiveRecordId(loadedRecords.find((record) => sameConfig(record, config))?.id ?? null);
      })
      .catch((err) => message.error(err instanceof Error ? err.message : "加载配置失败"))
      .finally(() => setRecordsLoading(false));
  }, [form, message]);

  const applyPreset = (provider: string) => {
    if (!editing) return;
    // 自定义模式保留当前内容，避免用户误点后丢失已经填写的接口信息。
    if (provider === CUSTOM_PRESET) return;
    const preset = LLM_PRESETS.find((item) => item.provider === provider);
    if (!preset) return;
    form.setFieldsValue({ base_url: preset.base_url, model: preset.model });
  };

  /** 收集表单值并剔除前端专用的 preset 字段 */
  const collectValues = async (): Promise<LLMConfig | null> => {
    try {
      const values = await form.validateFields();
      return configFromFormValues(values);
    } catch {
      return null;
    }
  };

  const save = async () => {
    if (!editing || saving || testing) return;
    const values = await collectValues();
    if (!values) return;
    setSaving(true);
    try {
      const saved = await saveLLMConfig(values);
      const nextValues = formValuesFromConfig(saved);
      form.setFieldsValue(nextValues);
      savedValues.current = nextValues;
      setActiveRecordId(records.find((record) => sameConfig(record, saved))?.id ?? null);
      setEditing(false);
      setTestResult(null);
      message.success("配置已保存，可在下方保存为记录");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (saving || testing) return;
    const values = await collectValues();
    if (!values) return;
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await testLLM(values));
    } catch (err) {
      setTestResult({
        ok: false,
        latency_ms: null,
        message: err instanceof Error ? err.message : "测试失败",
      });
    } finally {
      setTesting(false);
    }
  };

  const openRecordModal = () => {
    if (editing || recordSaving || !savedValues.current) return;
    setRecordName("");
    setRecordModalOpen(true);
  };

  const saveRecord = async () => {
    const name = recordName.trim();
    const saved = savedValues.current;
    if (!name) {
      message.warning("请填写配置记录名称");
      return;
    }
    if (!saved) {
      message.warning("当前配置尚未加载完成");
      return;
    }

    setRecordSaving(true);
    try {
      const record = await saveLLMConfigRecord({ name, ...configFromFormValues(saved) });
      setRecords((current) => [record, ...current.filter((item) => item.id !== record.id)]);
      setActiveRecordId(record.id);
      setRecordModalOpen(false);
      message.success("配置记录已保存");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存配置记录失败");
    } finally {
      setRecordSaving(false);
    }
  };

  const applyRecord = async (record: LLMConfigRecord) => {
    if (editing || saving || testing || recordApplyingId !== null) return;
    setRecordApplyingId(record.id);
    try {
      const saved = await saveLLMConfig(configFromRecord(record));
      const nextValues = formValuesFromConfig(saved);
      form.setFieldsValue(nextValues);
      savedValues.current = nextValues;
      setActiveRecordId(record.id);
      setTestResult(null);
      message.success(`已切换到配置「${record.name}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "切换配置失败");
    } finally {
      setRecordApplyingId(null);
    }
  };

  const removeRecord = async (record: LLMConfigRecord) => {
    if (recordDeletingId !== null || recordApplyingId !== null) return;
    setRecordDeletingId(record.id);
    try {
      await deleteLLMConfigRecord(record.id);
      setRecords((current) => current.filter((item) => item.id !== record.id));
      setActiveRecordId((current) => (current === record.id ? null : current));
      message.success("配置记录已删除");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除配置记录失败");
    } finally {
      setRecordDeletingId(null);
    }
  };

  const cancelEditing = () => {
    if (saving || testing) return;
    if (savedValues.current) {
      form.resetFields();
      form.setFieldsValue(savedValues.current);
    }
    setTestResult(null);
    setEditing(false);
  };

  return (
    <div className={`settings-page${editing ? " is-editing" : ""}`}>
      <div className="settings-page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            设置
          </Typography.Title>
          <Typography.Text type="secondary">
            配置简历生成、岗位需求解读和求职助手等 AI 功能使用的模型服务
          </Typography.Text>
        </div>
        <div className="profile-page-header-actions">
          {editing ? (
            <>
              <Button icon={<CloseOutlined />} disabled={saving || testing} onClick={cancelEditing}>
                取消
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                disabled={testing}
                onClick={() => void save()}
              >
                保存配置
              </Button>
            </>
          ) : (
            <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>
              编辑设置
            </Button>
          )}
        </div>
      </div>

      <Card title="大模型 API 配置" className="settings-card">
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="支持所有兼容 OpenAI Chat Completions 协议的模型服务：DeepSeek、豆包（火山方舟）、Kimi、智谱、OpenAI、Ollama 等。API Key 保存在本地数据库中，仅本机可访问。"
        />
        <Form form={form} layout="vertical" disabled={!editing || saving || testing}>
          <Form.Item name="preset" label="快速预设（选择后自动填充 Base URL 与模型名）">
            <Select options={PRESET_OPTIONS} onChange={applyPreset} />
          </Form.Item>
          <Row gutter={[16, 0]}>
            <Col xs={24} lg={16}>
              <Form.Item
                name="base_url"
                label="Base URL"
                rules={[{ required: true, message: "必填" }]}
                tooltip="服务地址，通常形如 https://api.xxx.com 或 https://api.xxx.com/v1"
              >
                <Input placeholder="https://api.deepseek.com" />
              </Form.Item>
            </Col>
            <Col xs={24} lg={8}>
              <Form.Item
                name="model"
                label="模型名称"
                rules={[{ required: true, message: "必填" }]}
                tooltip="各厂商模型名不同，请以官方文档为准"
              >
                <Input placeholder="deepseek-chat" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="api_key"
            label="API Key（选填）"
            tooltip="多数云模型服务需要填写；Ollama 等无需鉴权的本地兼容服务可留空。密钥仅保存在本机，并只发送给这里配置的模型服务。"
          >
            <Input.Password placeholder="sk-...（无需鉴权时可留空）" autoComplete="off" />
          </Form.Item>
          <Row gutter={[16, 0]}>
            <Col xs={24} md={8}>
              <Form.Item
                name="temperature"
                label="创意度 temperature"
                tooltip="控制输出的随机性。值越低越稳定，适合事实型简历；值越高表达更发散，也会增加内容不一致或虚构风险。"
              >
                <Slider min={0} max={2} step={0.1} marks={{ 0: "严谨", 1: "均衡", 2: "发散" }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="timeout_seconds"
                label="超时时间（秒）"
                tooltip="等待模型返回响应数据的最长时间；超过后请求会终止。网络较慢或生成内容较长时可适当调大，但调大不会让模型生成得更快。"
              >
                <InputNumber min={10} max={600} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="max_tokens"
                label="最大输出 Token"
                tooltip="限制模型单次回复的最大输出 Token 数。值越大可能增加费用；过小可能导致内容被截断。它不是模型的上下文长度上限。"
              >
                <InputNumber min={256} max={65536} step={512} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
        <Button
          icon={<ApiOutlined />}
          loading={testing}
          disabled={saving}
          onClick={() => void test()}
        >
          测试连接
        </Button>
        {testResult && (
          <Alert
            style={{ marginTop: 16 }}
            type={testResult.ok ? "success" : "error"}
            showIcon
            message={
              testResult.ok
                ? `${testResult.message}（耗时 ${testResult.latency_ms}ms）`
                : `连接失败：${testResult.message}`
            }
          />
        )}
      </Card>

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
            onClick={openRecordModal}
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
                  onClick={() => void applyRecord(record)}
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
                  onConfirm={() => void removeRecord(record)}
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
                    <Tag>{record.provider || "custom"}</Tag>
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
        onOk={() => void saveRecord()}
        onCancel={() => {
          if (!recordSaving) setRecordModalOpen(false);
        }}
      >
        <Form layout="vertical">
          <Form.Item label="记录名称" required style={{ marginBottom: 8 }}>
            <Input
              autoFocus
              maxLength={64}
              showCount
              value={recordName}
              placeholder="如：DeepSeek 校招、Ollama 本地模型"
              onChange={(event) => setRecordName(event.target.value)}
              onPressEnter={() => void saveRecord()}
            />
          </Form.Item>
          <Typography.Text type="secondary">
            只保存当前已保存的配置，不会保存未点击“保存配置”的编辑内容。
          </Typography.Text>
        </Form>
      </Modal>
    </div>
  );
}
