/** 大模型配置表单与连接测试入口。 */

import { ApiOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Slider,
  Tooltip,
} from "antd";
import type { FormInstance } from "antd/es/form";
import { useRef } from "react";
import type { LLMTestResult } from "../../types";
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
}: Props) {
  const maxTokens = Form.useWatch("max_tokens", form);
  const unlimitedTokens = maxTokens === UNLIMITED_MAX_TOKENS;
  // 记住勾选「不限制」之前的值，取消勾选时原样还回去，免得用户重填。
  const lastLimitedTokens = useRef(DEFAULT_MAX_TOKENS);

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

  return (
    <Card title="大模型 API 配置" className="settings-card">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="支持所有兼容 OpenAI Chat Completions 协议的模型服务：DeepSeek、豆包（火山方舟）、Kimi、智谱、OpenAI、Ollama 等。API Key 保存在本地数据库中，仅本机可访问。"
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
          <Select options={PRESET_OPTIONS} onChange={onPresetChange} />
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
    </Card>
  );
}
