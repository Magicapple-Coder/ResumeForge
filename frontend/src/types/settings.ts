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

/** 备份包里的元信息。 */
export interface BackupManifest {
  format: number;
  app: string;
  app_version: string;
  alembic_revision: string | null;
  exported_at: string;
  tables: Record<string, number>;
  api_key_included: boolean;
}

export interface BackupDatabaseInfo {
  alembic_revision: string | null;
  tables: Record<string, number>;
}

/** 上传备份包后返回的预览；确认之前不会改动任何数据。 */
export interface BackupPreview {
  token: string;
  size_bytes: number;
  manifest: BackupManifest;
  database: BackupDatabaseInfo;
  current_tables: Record<string, number>;
}

export interface BackupApplyResult {
  manifest: BackupManifest;
  tables: Record<string, number>;
  previous_backup: string | null;
  upgraded_backup: string | null;
}
