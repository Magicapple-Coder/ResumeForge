/** 前端常量配置：品牌信息与展示类配置集中在此。 */

export const APP_NAME = "简历通";
export const APP_NAME_EN = "ResumeForge";

/** 公开仓库地址可被部署环境覆盖；默认值用于开源发行版的导航入口。 */
export const GITHUB_REPO =
  import.meta.env.VITE_GITHUB_REPO?.trim() || "https://github.com/Magicapple-Coder/ResumeForge";

/** 大模型预设：选择后自动填充 Base URL 与模型名，省去查文档的麻烦 */
export interface LLMPreset {
  label: string;
  provider: string;
  base_url: string;
  model: string;
}

export const LLM_PRESETS: LLMPreset[] = [
  {
    label: "DeepSeek（深度求索）",
    provider: "deepseek",
    base_url: "https://api.deepseek.com",
    model: "deepseek-chat",
  },
  {
    label: "豆包（火山方舟）",
    provider: "doubao",
    base_url: "https://ark.cn-beijing.volces.com/api/v3",
    model: "doubao-seed-1-6-250615",
  },
  {
    label: "Kimi（月之暗面）",
    provider: "kimi",
    base_url: "https://api.moonshot.cn/v1",
    model: "kimi-k2-0711-preview",
  },
  {
    label: "OpenAI",
    provider: "openai",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
  },
  {
    label: "Ollama（本地部署）",
    provider: "ollama",
    base_url: "http://localhost:11434/v1",
    model: "qwen2.5:7b",
  },
];

/** 经历美化程度（与后端 GenerateOptions.enhancement_level 对应）。 */
export const RESUME_ENHANCEMENT_LEVELS = [
  {
    value: "light",
    label: "轻度",
    description: "优化措辞与重点，基本保持原有篇幅",
  },
  {
    value: "balanced",
    label: "均衡",
    description: "补足方法、技术细节与成果表达",
  },
  {
    value: "strong",
    label: "深度",
    description: "充分利用已有资料，强化岗位匹配度",
  },
] as const;

/**
 * 通用简历没有岗位可匹配，深度档的说明要换一个说法。
 *
 * 参数类型直接写联合类型，**不要**改成 `import type { EnhancementLevel } from "./types"`：
 * 实测只是加上那一行类型导入，`AssistantPage.test.tsx` 就从稳定通过变成 5/6 失败
 * （报错是空态元素刚找到就被卸载，像时序问题；去掉后 6/6 通过）。类型导入本身不该有
 * 运行时影响，具体机制没查清，所以这里保持不引入 `types/` barrel。
 */
export function enhancementLevelDescription(
  level: "light" | "balanced" | "strong",
  general = false,
): string {
  const matched = RESUME_ENHANCEMENT_LEVELS.find((item) => item.value === level);
  if (!matched) return "";
  if (!general || level !== "strong") return matched.description;
  return "充分利用已有资料，充分展开过程与成果";
}
