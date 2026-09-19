/** 内推管理接口。 */
import type { Referral, ReferralImageUpload, ReferralPayload, ReferralStats } from "../types";
import { ApiError, buildQuery, extractError, request } from "./client";

export function listReferrals(
  params: { status?: string; keyword?: string; limit?: number } = {},
): Promise<Referral[]> {
  return request(`/referrals${buildQuery(params)}`);
}

export function getReferralStats(): Promise<ReferralStats> {
  return request("/referrals/stats");
}

export function createReferral(payload: ReferralPayload): Promise<Referral> {
  return request("/referrals", { method: "POST", body: JSON.stringify(payload) });
}

export function updateReferral(id: number, payload: Partial<ReferralPayload>): Promise<Referral> {
  return request(`/referrals/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteReferral(id: number): Promise<void> {
  return request(`/referrals/${id}`, { method: "DELETE" });
}

/** 上传一张内推备注图片（multipart），返回相对路径。 */
export async function uploadReferralImage(file: File): Promise<ReferralImageUpload> {
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch("/api/referrals/upload-image", {
    method: "POST",
    body: formData,
  });
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return (await resp.json()) as ReferralImageUpload;
}
