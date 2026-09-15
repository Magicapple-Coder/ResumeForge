/** 求职助手 feature 内共享的展示类型。 */

export interface StarterPrompt {
  label: string;
  content: string;
  enableWebSearch?: boolean;
}

export const STARTER_PROMPTS: readonly StarterPrompt[] = [
  {
    label: "分析岗位匹配度",
    content: "请结合我选择的岗位和资料，分析我的匹配度，并给出准备建议。",
  },
  {
    label: "优化项目经历",
    content: "请帮我把我的项目经历改写得更贴合目标岗位，并保留真实事实。",
  },
  {
    label: "准备一轮面试",
    content: "请根据目标岗位模拟一轮面试，并逐题给出回答思路。",
  },
  {
    label: "查找招聘信息",
    content: "请帮我查找与目标方向相关的招聘信息，并优先给出官网链接。",
    enableWebSearch: true,
  },
] as const;

export type ConversationFilter = "all" | "favorite";
