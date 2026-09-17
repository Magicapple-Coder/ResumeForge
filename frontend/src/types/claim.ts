/**
 * 事实台账类型。
 *
 * 取值与后端 `models/claim.py` 的常量**逐字对应**——两处各写一份中文枚举最容易漂移，
 * 而这里的漂移会直接表现成"界面上能选、保存时 422"。改后端常量时这里必须同步。
 */

/** 承担程度：个人在这件事里的位置。 */
export const RESPONSIBILITY_LEVELS = ["参与", "负责模块", "主导方案或交付", "项目负责人"] as const;
export type ResponsibilityLevel = (typeof RESPONSIBILITY_LEVELS)[number];

/** 强主张：出现这两类时必须能回答追问，界面上给出提示。 */
export const STRONG_RESPONSIBILITY_LEVELS: readonly ResponsibilityLevel[] = [
  "主导方案或交付",
  "项目负责人",
];

/** 核实状态：决定这条主张能出现在哪一版材料里。 */
export const VERIFICATION_STATUSES = ["已确认", "待确认", "已过期", "不采用"] as const;
export type VerificationStatus = (typeof VERIFICATION_STATUSES)[number];

export const VERIFICATION_STATUS_HINTS: Record<VerificationStatus, string> = {
  已确认: "可以作为事实写进正式简历",
  待确认: "只能进草稿，必须保留【待补】占位符",
  已过期: "内容会随时间变化，更新前不作为最新事实",
  不采用: "保留原因供复盘，不进入对外材料",
};

export const CLAIM_CATEGORIES = [
  "教育经历",
  "实习/工作",
  "项目经历",
  "校园经历",
  "专业技能",
  "荣誉奖项",
  "其他",
] as const;
export type ClaimCategory = (typeof CLAIM_CATEGORIES)[number];

/** 证据来源：只记录"去哪儿能找到"，不存内容本身。 */
export const SOURCE_TYPES = [
  "pull_request",
  "repository",
  "document",
  "certificate",
  "link",
  "screenshot",
  "reference",
  "other",
] as const;
export type SourceType = (typeof SOURCE_TYPES)[number];

export const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  pull_request: "合并请求 / PR",
  repository: "代码仓库",
  document: "文档 / 报告",
  certificate: "证书 / 证明",
  link: "公开链接",
  screenshot: "截图",
  reference: "可联系的人 / 推荐人",
  other: "其他",
};

/**
 * 未完成占位符。与后端 `PLACEHOLDER_MARKERS` 保持一致：导出终稿时命中这些标记
 * 会被拦下，所以界面在编辑时就要把它标出来，别等导出才报错。
 */
export const PLACEHOLDER_MARKERS = ["【待补", "【待确认", "【待补充", "【待核实"] as const;

export function hasPlaceholder(text: string): boolean {
  return PLACEHOLDER_MARKERS.some((marker) => text.includes(marker));
}

export interface ClaimSource {
  type: SourceType;
  location: string;
  public: boolean;
  note: string;
}

export interface ClaimInterviewDetails {
  decisions: string[];
  difficulties: string[];
  verification: string[];
  result: string | null;
}

export interface Claim {
  id: number;
  title: string;
  category: ClaimCategory;
  subject: string;
  source_fact: string;
  candidate_wording: string;
  sources: ClaimSource[];
  responsibility_level: ResponsibilityLevel;
  verification_status: VerificationStatus;
  allowed_uses: string[];
  interview_details: ClaimInterviewDetails;
  boundary: string;
  risk_notes: string[];
  last_verified: string;
  created_at: string;
  updated_at: string;
  /** 服务端算出的改进建议（不是保存失败原因）。 */
  warnings: string[];
}

export type ClaimPayload = Omit<Claim, "id" | "created_at" | "updated_at" | "warnings">;

export interface ClaimList {
  items: Claim[];
  total: number;
  confirmed_count: number;
  pending_count: number;
  category_counts: Partial<Record<ClaimCategory, number>>;
}

/** 生成链路用的事实基线摘要。 */
export interface ClaimDigest {
  confirmed_count: number;
  baseline_text: string;
  blocked_wording: string[];
  warnings: string[];
}

export interface ClaimDraftPayload {
  category: ClaimCategory;
  subject: string;
  raw_text: string;
}

export interface ClaimDraft {
  drafts: ClaimPayload[];
  notes: string[];
}

/**
 * 从一条完整记录里取出可提交的字段（去掉服务端生成的 id、时间戳与建议）。
 *
 * 显式列字段而不是"解构后丢掉几个"：后者漏掉新字段时不会报错，只会静默把用户的
 * 输入丢掉——那是最难发现的一类毛病。
 */
export function claimPayload(claim: Claim, patch: Partial<ClaimPayload> = {}): ClaimPayload {
  return {
    title: claim.title,
    category: claim.category,
    subject: claim.subject,
    source_fact: claim.source_fact,
    candidate_wording: claim.candidate_wording,
    sources: claim.sources,
    responsibility_level: claim.responsibility_level,
    verification_status: claim.verification_status,
    allowed_uses: claim.allowed_uses,
    interview_details: claim.interview_details,
    boundary: claim.boundary,
    risk_notes: claim.risk_notes,
    last_verified: claim.last_verified,
    ...patch,
  };
}

/** 空条目的出厂值：新建时用它，避免各处各写一份默认值。 */
export function emptyClaim(): ClaimPayload {
  return {
    title: "",
    category: "项目经历",
    subject: "",
    source_fact: "",
    candidate_wording: "",
    sources: [],
    responsibility_level: "参与",
    verification_status: "待确认",
    allowed_uses: [],
    interview_details: { decisions: [], difficulties: [], verification: [], result: null },
    boundary: "",
    risk_notes: [],
    last_verified: "",
  };
}
