/** 离线分享包接口。 */
import type {
  ShareComments,
  SharePackageBrief,
  SharePackageCreatePayload,
  SharePackageDetail,
  ShareReveal,
} from "../types";
import { ApiError, extractError, getFilenameFromDisposition, request } from "./client";

export function listSharePackages(): Promise<SharePackageBrief[]> {
  return request("/share-packages");
}

export function createSharePackage(payload: SharePackageCreatePayload): Promise<SharePackageDetail> {
  return request("/share-packages", { method: "POST", body: JSON.stringify(payload) });
}

export function getSharePackage(id: number): Promise<SharePackageDetail> {
  return request(`/share-packages/${id}`);
}

/** 移入回收站（软删除）；彻底删除在「回收站」里另做。 */
export function deleteSharePackage(id: number): Promise<void> {
  return request(`/share-packages/${id}`, { method: "DELETE" });
}

/** 让服务端在文件管理器里打开该分享包所在目录（只接受 id，不接受任意路径）。 */
export function revealSharePackage(id: number): Promise<ShareReveal> {
  return request(`/share-packages/${id}/reveal`, { method: "POST" });
}

export function getSharePackageComments(id: number): Promise<ShareComments> {
  return request(`/share-packages/${id}/comments`);
}

export function importSharePackageComments(
  id: number,
  payload: { content: string; format: "markdown" | "json" },
): Promise<ShareComments> {
  return request(`/share-packages/${id}/comments/import`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** 下载分享包里的一个产物文件，返回 blob 与服务端建议的文件名。 */
export async function downloadSharePackageFile(
  id: number,
  filename: string,
): Promise<{ blob: Blob; filename: string }> {
  const resp = await fetch(`/api/share-packages/${id}/files/${encodeURIComponent(filename)}`);
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return {
    blob: await resp.blob(),
    filename: getFilenameFromDisposition(resp.headers.get("Content-Disposition")) ?? filename,
  };
}
