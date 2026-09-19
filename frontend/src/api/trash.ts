/**
 * 回收站接口：查看、恢复、彻底删除、清空。
 *
 * **恢复与彻底删除是两个函数**（对应后端两个接口）：它们对用户的风险完全不同——恢复是安全的、
 * 彻底删除不可逆。合成一个函数用参数区分，某次传错参数就变成不可逆操作，而界面上完全看不出来。
 */
import type { TrashEmptyResult, TrashSummary } from "../types";
import { buildQuery, request } from "./client";

export function getTrash(params: { type?: string } = {}): Promise<TrashSummary> {
  return request(`/trash${buildQuery(params)}`);
}

export function restoreTrashItem(type: string, id: number): Promise<void> {
  return request(`/trash/${type}/${id}/restore`, { method: "POST" });
}

/** **彻底删除**（不可恢复）。界面必须先让用户二次确认。 */
export function purgeTrashItem(type: string, id: number): Promise<void> {
  return request(`/trash/${type}/${id}`, { method: "DELETE" });
}

/** 清空回收站（不可恢复）。`type` 留空表示全部清空。 */
export function emptyTrash(type = ""): Promise<TrashEmptyResult> {
  return request(`/trash${buildQuery({ type })}`, { method: "DELETE" });
}
