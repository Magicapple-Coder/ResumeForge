/** ATS 本地检测（R-10）的类型。枚举字符串与后端 schemas/ats.py 逐字一致。 */

export type AtsIssueCategory = "format" | "keyword" | "position";
export type AtsSeverity = "high" | "medium" | "low";

export interface AtsIssue {
  category: AtsIssueCategory;
  severity: AtsSeverity;
  title: string;
  detail: string;
  evidence: string[];
}

export interface AtsCheckResult {
  resume_id: number;
  issues: AtsIssue[];
  matched_keywords: string[];
  missing_keywords: string[];
  /** 0~100 的粗略估计分，仅作参考。 */
  score: number;
  /** 免责声明，必须展示给用户。 */
  disclaimer: string;
  summary: Record<string, number>;
}
