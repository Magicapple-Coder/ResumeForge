/** 大模型设置、数据集与更新检查类型。 */

export interface LLMConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  timeout_seconds: number;
  max_tokens: number;
  /** 高级调整（可选）：null 表示不发送该参数，沿用服务商默认值。 */
  top_p: number | null;
  frequency_penalty: number | null;
  presence_penalty: number | null;
  seed: number | null;
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
