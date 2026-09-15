/** 设置页的预设、脱敏和表单值转换逻辑。 */

import { LLM_PRESETS } from "../../config";
import type { LLMConfig, LLMConfigRecord } from "../../types";

export const CUSTOM_PRESET = "custom";
export const CUSTOM_PRESET_LABEL = "自定义模型（OpenAI 兼容）";
export const API_KEY_MASK = "********";

export const PRESET_OPTIONS = [
  ...LLM_PRESETS.map((preset) => ({ value: preset.provider, label: preset.label })),
  { value: CUSTOM_PRESET, label: CUSTOM_PRESET_LABEL },
];

export type SettingsFormValues = LLMConfig & { preset: string };

export function normalizePresetBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  try {
    const url = new URL(trimmed);
    if (url.username || url.password || url.search || url.hash) return trimmed;
    const defaultPort =
      (url.protocol === "https:" && url.port === "443") ||
      (url.protocol === "http:" && url.port === "80");
    const port = url.port && !defaultPort ? `:${url.port}` : "";
    const path = url.pathname.replace(/\/+$/, "");
    return `${url.protocol.toLowerCase()}//${url.hostname.toLowerCase()}${port}${path}`;
  } catch {
    return trimmed;
  }
}

export function matchingPreset(config: Pick<LLMConfig, "provider" | "base_url">) {
  const normalizedUrl = normalizePresetBaseUrl(config.base_url);
  const exact = LLM_PRESETS.find(
    (preset) =>
      preset.provider === config.provider &&
      normalizePresetBaseUrl(preset.base_url) === normalizedUrl,
  );
  if (exact || config.provider !== CUSTOM_PRESET) return exact;
  // 早期自定义配置没有保存正确的展示标识；官方地址足以无歧义地恢复预设名称。
  return LLM_PRESETS.find((preset) => normalizePresetBaseUrl(preset.base_url) === normalizedUrl);
}

export function isMaskedApiKey(value: string): boolean {
  return value === API_KEY_MASK || value.startsWith(`${API_KEY_MASK}:record:`);
}

export function formValuesFromConfig(config: LLMConfig): SettingsFormValues {
  const matched = matchingPreset(config);
  return {
    provider: config.provider,
    base_url: config.base_url,
    api_key: config.api_key,
    model: config.model,
    temperature: config.temperature,
    timeout_seconds: config.timeout_seconds,
    max_tokens: config.max_tokens,
    preset: matched?.provider ?? CUSTOM_PRESET,
  };
}

export function configFromFormValues(values: SettingsFormValues): LLMConfig {
  return {
    provider: values.provider,
    base_url: values.base_url,
    api_key: values.api_key,
    model: values.model,
    temperature: values.temperature,
    timeout_seconds: values.timeout_seconds,
    max_tokens: values.max_tokens,
  };
}

export function configFromRecord(record: LLMConfigRecord): LLMConfig {
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

export function sameConfig(left: LLMConfig, right: LLMConfig): boolean {
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
