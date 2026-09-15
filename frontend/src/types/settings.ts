/** 大模型设置及连接测试结果类型。 */

export interface LLMConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  timeout_seconds: number;
  max_tokens: number;
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
