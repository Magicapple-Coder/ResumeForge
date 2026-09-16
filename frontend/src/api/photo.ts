/** 个人照片接口：多张照片的上传、切换、重命名与删除。 */
import type { ProfilePhoto } from "../types";
import { request } from "./client";

export function listProfilePhotos(): Promise<ProfilePhoto[]> {
  return request("/profile/photos");
}

export function createProfilePhoto(image: string, name = ""): Promise<ProfilePhoto> {
  return request("/profile/photos", {
    method: "POST",
    body: JSON.stringify({ image, name }),
  });
}

/** 重命名照片，或把它设为当前使用的照片（一次只提交其中一项即可）。 */
export function updateProfilePhoto(
  id: number,
  patch: { name?: string; is_primary?: boolean },
): Promise<ProfilePhoto> {
  return request(`/profile/photos/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteProfilePhoto(id: number): Promise<void> {
  return request(`/profile/photos/${id}`, { method: "DELETE" });
}
