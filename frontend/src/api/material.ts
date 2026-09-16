/** 资料箱接口：零散资料的增删改查。 */
import type { Material, MaterialPayload } from "../types";
import { buildQuery, request } from "./client";

export function listMaterials(
  params: { keyword?: string; category?: string } = {},
): Promise<Material[]> {
  return request(`/materials${buildQuery(params)}`);
}

/** 候选分类：内置分类 + 用户已用过的自定义分类。 */
export function listMaterialCategories(): Promise<string[]> {
  return request("/materials/categories");
}

export function getMaterial(id: number): Promise<Material> {
  return request(`/materials/${id}`);
}

export function createMaterial(payload: MaterialPayload): Promise<Material> {
  return request("/materials", { method: "POST", body: JSON.stringify(payload) });
}

export function updateMaterial(id: number, payload: MaterialPayload): Promise<Material> {
  return request(`/materials/${id}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function deleteMaterial(id: number): Promise<void> {
  return request(`/materials/${id}`, { method: "DELETE" });
}
