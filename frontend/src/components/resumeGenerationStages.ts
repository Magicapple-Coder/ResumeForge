/**
 * 简历生成进度条用的阶段表与文案映射。
 *
 * 为什么是「阶段条 + 已接收字数」，而不是百分比：模型输出是逐字流式返回的，后端
 * 无法预知总长度，任何百分比都只能靠猜；一个"看起来精确、其实是编的"百分比比没有
 * 进度更误导人。所以只呈现两件后端**真的知道**的事——走到第几步、已接收多少字。
 *
 * 阶段与后端 `services/resume_generator.py` 里真实 `progress` 事件一一对应：
 *   整理资料 → 筛选资料 → 调用模型 → [修复 / 改写] → 完成。
 * 「修复 / 改写」是同一阶段（都是生成之后的二次修正，且不一定会发生），合并成一个
 * 「校验修复」；映射不上的 `progress` 文案返回 null，前端只显示文字、不硬凑一个阶段。
 */

export type ResumeGenerationStageKey = "prepare" | "select" | "generate" | "repair" | "done";

export interface ResumeGenerationStage {
  key: ResumeGenerationStageKey;
  title: string;
  description: string;
}

export const RESUME_GENERATION_STAGES: ResumeGenerationStage[] = [
  { key: "prepare", title: "整理资料", description: "读取个人资料与岗位要求" },
  { key: "select", title: "筛选资料", description: "按篇幅预算挑选相关内容" },
  { key: "generate", title: "调用模型生成", description: "模型正在撰写简历正文" },
  { key: "repair", title: "校验修复", description: "修正格式或改写空话套话" },
  { key: "done", title: "完成", description: "结果已保存" },
];

const STAGE_INDEX = new Map<ResumeGenerationStageKey, number>(
  RESUME_GENERATION_STAGES.map((stage, index) => [stage.key, index]),
);

/** 返回阶段在阶段条里的序号；未知阶段回退到 0（第一步），不抛异常。 */
export function stageIndexOf(key: ResumeGenerationStageKey | null): number {
  if (key === null) return 0;
  return STAGE_INDEX.get(key) ?? 0;
}

/**
 * 把后端一条 `progress` 文案映射到阶段 key；映射不上返回 null。
 *
 * 匹配按「后端已写死的关键短语」精确判断，而不是模糊分词：文案是后端稳定常量，
 * 用包含关系就足够，还能在文案微调时保持宽松（例如模型名会插进"正在调用模型…"）。
 */
export function stageForProgressMessage(message: string): ResumeGenerationStageKey | null {
  const text = message.trim();
  if (text.includes("正在调用模型")) return "generate";
  if (text.includes("修复") || text.includes("改写") || text.includes("重新生成")) {
    return "repair";
  }
  if (text.startsWith("已整理") || text.startsWith("已从完整资料中筛选")) return "select";
  if (text.includes("整理") || text.includes("分析岗位要求")) return "prepare";
  return null;
}
