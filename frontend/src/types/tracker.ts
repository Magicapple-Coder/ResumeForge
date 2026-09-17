/**
 * 求职进度类型。
 *
 * 取值与后端 `models/tracker.py` 的常量**逐字对应**——两处各写一份最容易漂移，
 * 而这里的漂移会表现成"界面上能选、保存时 422"。
 */

/** 漏斗的七个状态。顺序就是漏斗的推进顺序，「已结束」和「待确认」不在主线上。 */
export const TRACK_STATUSES = [
  "applied",
  "screening",
  "assessment",
  "interview",
  "offer",
  "rejected",
  "unknown",
] as const;
export type TrackStatus = (typeof TRACK_STATUSES)[number];

export const TRACK_STATUS_LABELS: Record<TrackStatus, string> = {
  applied: "已投递",
  screening: "筛选中",
  assessment: "测评/笔试",
  interview: "面试",
  offer: "Offer",
  rejected: "已结束",
  unknown: "待确认",
};

/** 漏斗主线（按推进顺序），「已结束」「待确认」不属于主线。 */
export const FUNNEL_STATUSES: readonly TrackStatus[] = [
  "applied",
  "screening",
  "assessment",
  "interview",
  "offer",
];

export const TRACK_STATUS_COLORS: Record<TrackStatus, string> = {
  applied: "default",
  screening: "blue",
  assessment: "cyan",
  interview: "purple",
  offer: "green",
  rejected: "red",
  unknown: "gold",
};

/** 进行中：还没走到终态的，界面上要突出。 */
export const ACTIVE_TRACK_STATUSES: readonly TrackStatus[] = [
  "applied",
  "screening",
  "assessment",
  "interview",
];

export function isActiveStatus(status: TrackStatus): boolean {
  return ACTIVE_TRACK_STATUSES.includes(status);
}

/** 记录来源：区分"投递台自动记的"和"我自己加的/识别导入的"。 */
export const TRACK_SOURCES = ["apply", "manual", "recognized"] as const;
export type TrackSource = (typeof TRACK_SOURCES)[number];

export const TRACK_SOURCE_LABELS: Record<TrackSource, string> = {
  apply: "投递台自动记录",
  manual: "手动添加",
  recognized: "识别导入",
};

/** 合并结论：这次识别对这条记录做了什么。 */
export const MERGE_ACTIONS = ["created", "updated", "unchanged"] as const;
export type MergeAction = (typeof MERGE_ACTIONS)[number];

export const MERGE_ACTION_LABELS: Record<MergeAction, string> = {
  created: "新增记录",
  updated: "更新进度",
  unchanged: "已是最新，未改动",
};

export const MERGE_ACTION_COLORS: Record<MergeAction, string> = {
  created: "green",
  updated: "blue",
  unchanged: "default",
};

export interface TrackRecord {
  company: string;
  title: string;
  status: TrackStatus;
  stage_note: string;
  applied_at: string;
  status_date: string;
  next_action: string;
  next_action_date: string;
  note: string;
  evidence: string;
}

export interface Track extends TrackRecord {
  id: number;
  source: TrackSource;
  created_at: string;
  updated_at: string;
  job_id: number | null;
  resume_id: number | null;
}

export type TrackPayload = Omit<Track, "id" | "source" | "created_at" | "updated_at">;

export interface TrackList {
  items: Track[];
  total: number;
  status_counts: Record<string, number>;
  active_count: number;
  offer_count: number;
  rejected_count: number;
  month_count: number;
}

/** 一条识别结果的合并预览：会新增、会更新，还是没变化。 */
export interface TrackMergePreview {
  record: TrackRecord;
  action: MergeAction;
  reason: string;
  current_status: string;
}

export interface TrackParseResult {
  items: TrackMergePreview[];
  parse_engine: "ai" | "local";
  notes: string[];
}

export interface TrackApplyResultItem {
  company: string;
  title: string;
  action: string;
  status: string;
  reason: string;
}

export interface TrackApplyResult {
  items: TrackApplyResultItem[];
  created: number;
  updated: number;
  unchanged: number;
}

export function emptyTrack(): TrackPayload {
  return {
    company: "",
    title: "",
    status: "applied",
    stage_note: "",
    applied_at: "",
    status_date: "",
    next_action: "",
    next_action_date: "",
    note: "",
    evidence: "",
    job_id: null,
    resume_id: null,
  };
}

/**
 * 从一条完整记录里取出可提交的字段（去掉服务端生成的 id、时间戳与来源）。
 *
 * 显式列字段而不是"解构后丢掉几个"：后者漏掉新字段时不会报错，只会静默把用户的
 * 输入丢掉——那是最难发现的一类毛病。
 */
export function trackPayload(track: Track, patch: Partial<TrackPayload> = {}): TrackPayload {
  return {
    company: track.company,
    title: track.title,
    status: track.status,
    stage_note: track.stage_note,
    applied_at: track.applied_at,
    status_date: track.status_date,
    next_action: track.next_action,
    next_action_date: track.next_action_date,
    note: track.note,
    evidence: track.evidence,
    job_id: track.job_id,
    resume_id: track.resume_id,
    ...patch,
  };
}
