/** 大模型设置、数据集与更新检查类型。 */

/** 接口协议：Claude 也能走 OpenAI 兼容层（openai），或原生 Messages 协议（anthropic）。 */
export type LLMApiStyle = "openai" | "anthropic";

/** 额外请求体字段允许的值：任意 JSON 值（对象与数组都算 object）。 */
export type LLMExtraBodyValue = string | number | boolean | object;

/**
 * 大模型配置。
 *
 * **每个后端字段都必须在这里出现**：设置接口是整份替换语义，前端没声明的字段会在
 * 保存时被 Pydantic 的默认值填回去——此前 `api_style` 等六个字段没声明，用户在设置页
 * 点一次保存就会把原生 Anthropic 配置打回 `openai`，且没有任何提示。
 */
export interface LLMConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  timeout_seconds: number;
  max_tokens: number;
  api_style: LLMApiStyle;
  /** 高级调整（可选）：null 表示不发送该参数，沿用服务商默认值。 */
  top_p: number | null;
  frequency_penalty: number | null;
  presence_penalty: number | null;
  seed: number | null;
  top_k: number | null;
  repetition_penalty: number | null;
  /** 停止词：命中即让模型停下，最多 4 条。 */
  stop: string[];
  /** Anthropic 扩展思考预算（tokens）；0 = 明确关闭，null = 不发送。 */
  thinking_budget: number | null;
  /**
   * 长尾参数的出口：直接并进请求体。没有界面控件，但必须原样往返，否则会被清空。
   *
   * 值类型写 `LLMExtraBodyValue` 而不是 `unknown`：antd 的 Form 要求表单值的每一项都能
   * 赋给 `{}`，`unknown` 不满足，会让整个表单类型报错。
   */
  extra_body: Record<string, LLMExtraBodyValue>;
}

export interface LLMConfigRecord extends LLMConfig {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface LLMTestResult {
  ok: boolean;
  latency_ms: number | null;
  message: string;
}

export interface LLMApiKeyRevealResult {
  api_key: string;
}

/** 「获取可用模型」结果。失败时 message 说明原因，models 为空。 */
export interface LLMModelsResult {
  models: string[];
  message: string;
}

/** 一份数据集：一整个数据库，可切换。 */
export interface DatasetInfo {
  id: string;
  name: string;
  source: string;
  size_bytes: number;
  created_at: string | null;
  is_active: boolean;
  exists: boolean;
}

/** 更新检查结果：只对比版本，不执行任何自动更新。 */
export interface UpdateCheckResult {
  current_version: string;
  latest_version: string;
  update_available: boolean;
  release_name: string;
  release_url: string;
  published_at: string;
  notes: string;
  message: string;
  checked_at: string | null;
}
