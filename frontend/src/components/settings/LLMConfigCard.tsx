/** 大模型配置表单：预设、连接测试、获取可用模型与高级调整。 */

import { ApiOutlined, CloudDownloadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Row,
  Select,
  Slider,
  Tooltip,
  Typography,
} from "antd";
import type { FormInstance } from "antd/es/form";
import { useRef, useState } from "react";
import type { LLMModelsResult, LLMTestResult } from "../../types";
import ApiKeyInput from "./ApiKeyInput";
import {
  DEFAULT_MAX_TOKENS,
  MAX_MAX_TOKENS,
  MIN_MAX_TOKENS,
  PRESET_OPTIONS,
  UNLIMITED_MAX_TOKENS,
  type SettingsFormValues,
} from "./SettingsConfig";

interface Props {
  form: FormInstance<SettingsFormValues>;
  editing: boolean;
  saving: boolean;
  testing: boolean;
  testResult: LLMTestResult | null;
  apiKeyResetToken: number;
  onPresetChange: (provider: string) => void;
  onResetApiKey: () => void;
  onRevealApiKey: () => Promise<string>;
  onRevealError: (message: string) => void;
  onTest: () => void;
  /** 拉取服务商当前可用的模型列表（失败时由 result.message 说明原因）。 */
  onFetchModels: () => Promise<LLMModelsResult>;
}

export default function LLMConfigCard({
  form,
  editing,
  saving,
  testing,
  testResult,
  apiKeyResetToken,
  onPresetChange,
  onResetApiKey,
  onRevealApiKey,
  onRevealError,
  onTest,
  onFetchModels,
}: Props) {
  const maxTokens = Form.useWatch("max_tokens", form);
  const unlimitedTokens = maxTokens === UNLIMITED_MAX_TOKENS;
  // 记住勾选「不限制」之前的值，取消勾选时原样还回去，免得用户重填。
  const lastLimitedTokens = useRef(DEFAULT_MAX_TOKENS);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelsMessage, setModelsMessage] = useState("");

  const setUnlimitedTokens = (unlimited: boolean) => {
    if (unlimited) {
      // 只在写入 0 之前读取：此时字段里还是用户原本填的有限值。
      const current = form.getFieldValue("max_tokens");
      if (typeof current === "number" && current >= MIN_MAX_TOKENS) {
        lastLimitedTokens.current = current;
      }
    }
    form.setFieldValue("max_tokens", unlimited ? UNLIMITED_MAX_TOKENS : lastLimitedTokens.current);
  };

  const fetchModels = async () => {
    if (fetchingModels) return;
    setFetchingModels(true);
    try {
      const result = await onFetchModels();
      setModelsMessage(result.message);
      if (result.models.length > 0) {
        setModelOptions(result.models);
        setModelPickerOpen(true);
      }
    } finally {
      setFetchingModels(false);
    }
  };

  return (
    <Card title="大模型 API 配置" className="settings-card">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="支持所有兼容 OpenAI Chat Completions 协议的模型服务：DeepSeek、豆包（火山方舟）、Kimi、通义千问、智谱、MiniMax、硅基流动、OpenRouter、OpenAI、Gemini、Ollama 等。API Key 保存在本地数据库中，仅本机可访问。"
      />
      <Form
        form={form}
        layout="vertical"
        disabled={!editing || saving || testing}
        onValuesChange={(changedValues) => {
          if ("base_url" in changedValues) onResetApiKey();
        }}
      >
        <Form.Item name="provider" hidden>
          <Input />
        </Form.Item>
        <Form.Item name="preset" label="快速预设（选择后自动填充 Base URL 与模型名）">
          <Select
            options={PRESET_OPTIONS}
            onChange={onPresetChange}
            showSearch
            optionFilterProp="label"
          />
        </Form.Item>
        <Form.Item
          name="api_style"
          label="接口协议"
          tooltip="多数服务商（含 Claude 的 OpenAI 兼容层）走 Chat Completions，选「OpenAI 兼容」。只有要用 Claude 原生 Messages 协议（支持扩展思考、独立 system 字段）时才选 Anthropic 原生——此时 Base URL 填 https://api.anthropic.com。"
        >
          <Select
            options={[
              { value: "openai", label: "OpenAI 兼容（Chat Completions）" },
              { value: "anthropic", label: "Anthropic 原生（Messages）" },
            ]}
          />
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
              tooltip="各厂商模型名不同：可以点输入框右侧的「获取可用模型」按当前账号拉取，也可以照官方文档手填"
            >
              {/* 按钮放输入框的后缀里，不放 label 里也不另包一层：进 label 的按钮会被算成
                  「模型名称」标注的控件，而包一层（如 Space.Compact）会让 Form.Item 生成的
                  id 落在那层 div 上，label 就指不到输入框了。addonAfter 两种问题都没有。 */}
              <Input
                placeholder="deepseek-chat"
                addonAfter={
                  <Button
                    type="text"
                    size="small"
                    className="llm-fetch-models-button"
                    icon={<CloudDownloadOutlined />}
                    loading={fetchingModels}
                    onClick={() => void fetchModels()}
                  >
                    获取可用模型
                  </Button>
                }
              />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="api_key"
          label="API Key（选填）"
          tooltip="多数云模型服务需要填写；Ollama 等无需鉴权的本地兼容服务可留空。点击眼睛时才会从本机后端临时读取已保存密钥，隐藏后立即清除显示值。"
        >
          <ApiKeyInput
            editing={editing}
            disabled={saving || testing}
            resetToken={apiKeyResetToken}
            onReveal={onRevealApiKey}
            onRevealError={onRevealError}
          />
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
              tooltip="限制模型单次回复的最大输出 Token 数。值越大可能增加费用；过小可能导致内容被截断。它不是模型的上下文长度上限。勾选「不限制」后不再发送该参数，改由服务商决定上限，但并非真的无限——部分服务商的默认值可能比手动设置的值更小。"
            >
              <InputNumber
                min={MIN_MAX_TOKENS}
                max={MAX_MAX_TOKENS}
                step={512}
                // 要传 undefined 而不是 false：antd 只在 prop 为 null/undefined 时
                // 才回退到 Form 的 disabled 上下文，传 false 会让非编辑态也能改。
                disabled={unlimitedTokens ? true : undefined}
                style={{ width: "100%" }}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              {/* 这一条的行为与直觉相反（"不限制"其实取决于服务商默认值，可能比手填的还小），
                  而那段解释原本只挂在上面那个数字输入框的 tooltip 里，勾选框自己不说。 */}
              <Tooltip title="勾选后不再发送 max_tokens，由服务商决定上限。可缓解推理模型把思考过程算进输出预算、正文被挤空的问题；但它不是真的无限——部分服务商的默认值可能比手动设置的值更小。">
                <Checkbox
                  checked={unlimitedTokens}
                  onChange={(event) => setUnlimitedTokens(event.target.checked)}
                >
                  不限制（由服务商决定上限）
                </Checkbox>
              </Tooltip>
            </Form.Item>
          </Col>
        </Row>

        <Button
          type="link"
          className="llm-advanced-toggle"
          onClick={() => setAdvancedOpen((current) => !current)}
        >
          {advancedOpen
            ? "收起高级调整"
            : "高级调整（Top P / Top K、惩罚项、随机种子、停止词、思考预算）"}
        </Button>
        {advancedOpen && (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="留空的参数不会发送给模型服务，由服务商使用默认值。这些参数并非所有服务商都支持，填写前请先看官方文档。"
            />
            <Row gutter={[16, 0]}>
              <Col xs={24} md={6}>
                <Form.Item
                  name="top_p"
                  label="Top P"
                  tooltip="核采样：只从累计概率达到该值的候选里取词。与 temperature 叠加使用，通常只调其中一个。"
                >
                  <InputNumber
                    min={0}
                    max={1}
                    step={0.05}
                    style={{ width: "100%" }}
                    placeholder="留空 = 不发送"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={6}>
                <Form.Item
                  name="frequency_penalty"
                  label="频率惩罚"
                  tooltip="-2 到 2。正值降低重复用词，负值鼓励重复。"
                >
                  <InputNumber
                    min={-2}
                    max={2}
                    step={0.1}
                    style={{ width: "100%" }}
                    placeholder="留空 = 不发送"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={6}>
                <Form.Item
                  name="presence_penalty"
                  label="存在惩罚"
                  tooltip="-2 到 2。正值鼓励谈新话题，负值让模型更贴题。"
                >
                  <InputNumber
                    min={-2}
                    max={2}
                    step={0.1}
                    style={{ width: "100%" }}
                    placeholder="留空 = 不发送"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={6}>
                <Form.Item
                  name="seed"
                  label="随机种子"
                  tooltip="固定种子后同一请求更容易复现相同输出；是否生效取决于服务商。"
                >
                  <InputNumber
                    min={0}
                    step={1}
                    style={{ width: "100%" }}
                    placeholder="留空 = 不发送"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={6}>
                <Form.Item
                  name="top_k"
                  label="Top K"
                  tooltip="只在概率最高的 K 个候选里取词。Anthropic 与部分开源模型支持；OpenAI 官方接口会忽略它。"
                >
                  <InputNumber
                    min={0}
                    max={1000}
                    step={1}
                    style={{ width: "100%" }}
                    placeholder="留空 = 不发送"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={6}>
                <Form.Item
                  name="repetition_penalty"
                  label="重复惩罚"
                  tooltip="大于 1 时抑制重复用词。与「频率惩罚」作用类似但计算方式不同，通常只用其中一个。"
                >
                  <InputNumber
                    min={0}
                    max={2}
                    step={0.05}
                    style={{ width: "100%" }}
                    placeholder="留空 = 不发送"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={6}>
                <Form.Item
                  name="thinking_budget"
                  label="思考预算"
                  tooltip="Claude 原生协议下的扩展思考 token 预算。填 0 = 明确关闭思考；留空 = 不发送该字段。仅在协议选「Anthropic 原生」时有效。"
                >
                  <InputNumber
                    min={0}
                    max={100000}
                    step={1024}
                    style={{ width: "100%" }}
                    placeholder="留空 = 不发送"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name="stop"
                  label="停止词"
                  tooltip="模型生成到这些词就停下（最多 4 条）。回车确认一条；留空 = 不发送。"
                >
                  <Select
                    mode="tags"
                    open={false}
                    suffixIcon={null}
                    placeholder="输入后回车添加，最多 4 条"
                  />
                </Form.Item>
              </Col>
            </Row>
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 4 }}
              message="协议换成「Anthropic 原生」后，思考预算、Top K 等参数才有意义；换成 OpenAI 兼容时它们会被忽略。"
            />
          </>
        )}
      </Form>
      <Button icon={<ApiOutlined />} loading={testing} disabled={saving} onClick={onTest}>
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
      <Modal
        title="选择模型"
        open={modelPickerOpen}
        footer={null}
        onCancel={() => setModelPickerOpen(false)}
      >
        <Typography.Paragraph type="secondary">{modelsMessage}</Typography.Paragraph>
        <List
          size="small"
          dataSource={modelOptions}
          style={{ maxHeight: 360, overflowY: "auto" }}
          renderItem={(model) => (
            <List.Item
              actions={[
                <Button
                  key="pick"
                  type="link"
                  size="small"
                  onClick={() => {
                    form.setFieldValue("model", model);
                    setModelPickerOpen(false);
                  }}
                >
                  使用
                </Button>,
              ]}
            >
              <Typography.Text code>{model}</Typography.Text>
            </List.Item>
          )}
        />
      </Modal>
    </Card>
  );
}
