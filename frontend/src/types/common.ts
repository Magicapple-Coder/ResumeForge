/** 跨领域共享的基础类型。 */

export interface Page<T> {
  items: T[];
  total: number;
}

export interface SkillTag {
  name: string;
  category: string;
}
