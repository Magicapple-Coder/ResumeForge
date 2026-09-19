/** 内推管理（后端 /api/referrals）。 */

export const REFERRAL_STATUSES = ["active", "submitted", "closed", "invalid"] as const;
export type ReferralStatus = (typeof REFERRAL_STATUSES)[number];

export const REFERRAL_STATUS_LABELS: Record<ReferralStatus, string> = {
  active: "已联系",
  submitted: "已提交",
  closed: "已关闭",
  invalid: "无效",
};

/** 状态分色（antd Tag color）：active=蓝 / submitted=绿 / closed=灰 / invalid=红。 */
export const REFERRAL_STATUS_COLORS: Record<ReferralStatus, string> = {
  active: "blue",
  submitted: "green",
  closed: "default",
  invalid: "red",
};

export interface Referral {
  id: number;
  job_id: number | null;
  job_title: string;
  company: string;
  referrer_name: string;
  referrer_contact: string;
  relation: string;
  position: string;
  channel: string;
  status: string;
  track_id: number | null;
  /** 由关联漏斗后置位派生（进入面试及以上才为真）。 */
  converted: boolean;
  submitted_at: string;
  note: string;
  referral_code: string;
  note_images: string[];
  created_at: string;
  updated_at: string;
}

export interface ReferralPayload {
  job_id?: number | null;
  job_title?: string;
  company?: string;
  referrer_name?: string;
  referrer_contact?: string;
  relation?: string;
  position?: string;
  channel?: string;
  status?: ReferralStatus;
  track_id?: number | null;
  submitted_at?: string;
  note?: string;
  referral_code?: string;
  note_images?: string[];
}

export interface ReferralImageUpload {
  path: string;
}

/** 把内推备注图片的相对路径转成可请求的接口地址（只取最后一段，防穿越）。 */
export function referralImageUrl(path: string): string {
  const name = path.split(/[\\/]/).pop() ?? "";
  return `/api/referrals/images/${encodeURIComponent(name)}`;
}

export interface ReferralStats {
  total: number;
  converted: number;
  rate: number;
}
