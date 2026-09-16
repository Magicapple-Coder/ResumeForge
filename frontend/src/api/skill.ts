/** 助手技能接口：列出、导入、启用/停用与删除。 */
import { ApiError, extractError, request } from "./client";
import type { AssistantSkill } from "../types";

export function listSkills(): Promise<AssistantSkill[]> {
  return request("/assistant/skills");
}

/**
 * 导入一份技能：单个 `.md`（只有提示词）或一个 `.zip`（提示词 + 知识文件）。
 *
 * `Content-Type` 写死并用文件名区分，不信浏览器给的 `File.type`——系统映射给出的
 * 类型不可靠，而后端的类型白名单是拒绝导入的唯一依据。
 *
 * 请求体是裸文件字节，文件名不在里面，所以额外用一个头带上它：没有它，后端只能用
 * 随机临时文件名当技能名，而且同一个文件反复导入会变成一堆新技能而不是覆盖更新。
 * 头只能放 latin-1，中文文件名必须先编码。
 */
export async function importSkill(file: File): Promise<AssistantSkill> {
  const contentType = /\.zip$/i.test(file.name) ? "application/zip" : "text/markdown";
  const resp = await fetch("/api/assistant/skills/import", {
    method: "POST",
    headers: {
      "Content-Type": contentType,
      "X-Skill-Filename": encodeURIComponent(file.name),
    },
    body: file,
  });
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return (await resp.json()) as AssistantSkill;
}

export function setSkillEnabled(id: number, enabled: boolean): Promise<AssistantSkill> {
  return request(`/assistant/skills/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export function deleteSkill(id: number): Promise<void> {
  return request(`/assistant/skills/${id}`, { method: "DELETE" });
}
