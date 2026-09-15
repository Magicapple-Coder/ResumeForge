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
