/** 事实台账接口：条目增删改查、事实基线，以及从一段资料草拟条目。 */
import type {
  Claim,
  ClaimDigest,
  ClaimDraft,
  ClaimDraftPayload,
  ClaimList,
  ClaimPayload,
} from "../types";
import { buildQuery, request } from "./client";

export function listClaims(
  params: { category?: string; status?: string; keyword?: string } = {},
): Promise<ClaimList> {
  return request(`/claims${buildQuery(params)}`);
}

export function getClaim(id: number): Promise<Claim> {
  return request(`/claims/${id}`);
}

export function createClaim(payload: ClaimPayload): Promise<Claim> {
  return request("/claims", { method: "POST", body: JSON.stringify(payload) });
}

export function updateClaim(id: number, payload: ClaimPayload): Promise<Claim> {
  return request(`/claims/${id}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function deleteClaim(id: number): Promise<void> {
  return request(`/claims/${id}`, { method: "DELETE" });
}

/** 当前可用于生成的事实基线（已确认事实 + 必须避开的未确认说法）。 */
export function getClaimBaseline(): Promise<ClaimDigest> {
  return request("/claims/baseline");
}

/** 按一段资料草拟条目；只返回草稿，不落库。 */
export function draftClaims(payload: ClaimDraftPayload): Promise<ClaimDraft> {
  return request("/claims/draft", { method: "POST", body: JSON.stringify(payload) });
}
