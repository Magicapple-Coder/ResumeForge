/** 简历写作增强（R-04~R-07）与版本对比的类型。枚举字符串与后端逐字一致。 */

export type PolishStyle = "big_tech" | "concise_tech" | "campus";
export type TranslateDirection = "zh2en" | "en2zh";
export type PhraseMode = "star" | "resume" | "interview";

export interface StarRewriteResult {
  result: string;
}

export interface PhrasesResult {
  star: string;
  resume: string;
  interview: string;
}

export interface PolishResult {
  result: string;
}

export interface TranslateResult {
  result: string;
}

export type DiffLineType = "added" | "removed" | "unchanged";

/** 词级差异的最小单元。 */
export interface DiffToken {
  type: DiffLineType;
  text: string;
}

/** 一行差异：整行三态 + 可选的行内词级三态（仅对被改写的成对行）。 */
export interface DiffLine {
  type: DiffLineType;
  text: string;
  tokens: DiffToken[];
}

export interface DiffStats {
  added: number;
  removed: number;
  unchanged: number;
}

export interface ResumeDiff {
  base_id: number;
  against_id: number;
  base_title: string;
  against_title: string;
  lines: DiffLine[];
  stats: DiffStats;
}
