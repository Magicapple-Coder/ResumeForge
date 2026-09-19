/** 简历风险扫描（R-08 查重/敏感词/夸大/深挖风险点 + R-09 合规校验）的类型。
 *
 * 枚举字符串与后端 schemas/resume_risk.py 逐字一致（共享知识第 15 条）。
 */

export type RiskCategory =
  | "duplicate"
  | "sensitive"
  | "exaggeration"
  | "deep_dive"
  | "compliance";

export type RiskSeverity = "high" | "medium" | "low";

export interface RiskPoint {
  category: RiskCategory;
  severity: RiskSeverity;
  /** 命中的原文片段。 */
  text: string;
  /** 命中位置说明，如「项目经历「xx」」。 */
  location: string;
  /** 给用户的建议（只提示，不自动改写）。 */
  suggestion: string;
  /** 深挖风险点联动事实台账时回填的条目 id。 */
  claim_id: number | null;
  /** 强主张联动时回填的「会被追问什么」清单。 */
  follow_up: string[];
}

export interface ResumeRiskScan {
  resume_id: number;
  points: RiskPoint[];
  summary: Record<string, number>;
  llm_used: boolean;
  notes: string[];
}
