/** 离线分享包（后端 /api/share-packages，R-18）。 */
import type { RedactionOptions } from "./export";

/** 分享权限（与后端 ``SHARE_PERMISSIONS`` 逐字一致）。 */
export const SHARE_PERMISSIONS = ["read_only", "comment"] as const;
export type SharePermission = (typeof SHARE_PERMISSIONS)[number];

export interface ShareFile {
  name: string;
  path: string;
  format: string;
  size: number;
  sha256: string;
  /** 下载用的相对链接（后端拼好）。 */
  download_url: string;
}

export interface SharePackageBrief {
  id: number;
  title: string;
  resume_id: number | null;
  job_id: number | null;
  permission: string;
  file_count: number;
  created_at: string;
  updated_at: string;
}

export interface SharePackageDetail {
  id: number;
  title: string;
  resume_id: number | null;
  job_id: number | null;
  permission: string;
  files: ShareFile[];
  /** 只读 ResumeContent 快照（脱敏后、不含照片）。 */
  snapshot: Record<string, unknown>;
  comments_file: string;
  share_token: string;
  redaction_config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ShareComments {
  filename: string;
  format: "markdown" | "json";
  content: string;
}

export interface SharePackageCreatePayload {
  resume_id: number;
  permission: SharePermission;
  redact_options?: RedactionOptions;
}

export interface ShareReveal {
  /** 该分享包自己的本地目录（由服务端解析，前端不传任意路径）。 */
  directory: string;
}
