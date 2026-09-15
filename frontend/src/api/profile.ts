/** 个人资料接口。 */
import type { ExtractionImageInput, Profile, ProfileTextParseResult } from "../types";
import { request } from "./client";

export function getProfile(): Promise<Profile> {
  return request("/profile");
}

export function saveProfile(profile: Omit<Profile, "id" | "updated_at">): Promise<Profile> {
  return request("/profile", { method: "PUT", body: JSON.stringify(profile) });
}

export function parseProfileText(payload: {
  text: string;
  images?: ExtractionImageInput[];
}): Promise<ProfileTextParseResult> {
  return request("/profile/parse-text", { method: "POST", body: JSON.stringify(payload) });
}
