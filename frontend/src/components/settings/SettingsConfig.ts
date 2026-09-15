/** 设置页的预设、脱敏和表单值转换逻辑。 */

import { LLM_PRESETS } from "../../config";
import type { LLMConfig, LLMConfigRecord } from "../../types";

export const CUSTOM_PRESET = "custom";
export const CUSTOM_PRESET_LABEL = "自定义模型（OpenAI 兼容）";
/**
 * 不套用任何预设：选中后清空 Base URL 与模型名，由用户从空白开始填。
 *
 * 与 ``CUSTOM_PRESET`` 的区别只在"选中时做什么"：自定义模型保留当前内容（避免误点丢失
 * 已填的接口信息），纯手动配置则主动清空，用来从中转/网关等非标准地址重新填一套。
 * 两者都只影响表单，保存与否仍由用户决定。
 */
export const MANUAL_PRESET = "manual";
export const MANUAL_PRESET_LABEL = "纯手动配置（不套用任何预设）";
export const API_KEY_MASK = "********";

/** max_tokens 取该值表示“不限制”：请求体里不发送该字段，由服务商决定上限。 */
export const UNLIMITED_MAX_TOKENS = 0;
/** 取消“不限制”时回填的值，与后端 LLMConfig 的默认值保持一致。 */
export const DEFAULT_MAX_TOKENS = 4096;
export const MIN_MAX_TOKENS = 256;
export const MAX_MAX_TOKENS = 65536;

export const PRESET_OPTIONS = [
  ...LLM_PRESETS.map((preset) => ({ value: preset.provider, label: preset.label })),
  { value: CUSTOM_PRESET, label: CUSTOM_PRESET_LABEL },
  { value: MANUAL_PRESET, label: MANUAL_PRESET_LABEL },
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
    // 纯手动配置保存后再打开时，下拉要停在它自己那一项上，而不是跳回"自定义模型"。
    preset:
      matched?.provider ?? (config.provider === MANUAL_PRESET ? MANUAL_PRESET : CUSTOM_PRESET),
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
