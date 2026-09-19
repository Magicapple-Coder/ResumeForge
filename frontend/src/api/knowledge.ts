/** 知识库接口：条目的增删改查。 */
import type { Knowledge, KnowledgePayload } from "../types";
import { buildQuery, request } from "./client";

export function listKnowledge(
  params: { q?: string; category?: string } = {},
): Promise<Knowledge[]> {
  return request(`/knowledge${buildQuery(params)}`);
}

/** 候选分类：内置分类 + 用户已用过的自定义分类。 */
export function listKnowledgeCategories(): Promise<string[]> {
  return request("/knowledge/categories");
}

export function getKnowledge(id: number): Promise<Knowledge> {
  return request(`/knowledge/${id}`);
}

export function createKnowledge(payload: KnowledgePayload): Promise<Knowledge> {
  return request("/knowledge", { method: "POST", body: JSON.stringify(payload) });
}

export function updateKnowledge(id: number, payload: KnowledgePayload): Promise<Knowledge> {
  return request(`/knowledge/${id}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function deleteKnowledge(id: number): Promise<void> {
  return request(`/knowledge/${id}`, { method: "DELETE" });
}
