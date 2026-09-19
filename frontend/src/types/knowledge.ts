/** 知识库条目类型。 */

export interface Knowledge {
  id: number;
  title: string;
  category: string;
  tags: string[];
  content: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgePayload {
  title: string;
  category: string;
  tags: string[];
  content: string;
  source: string;
}

/** 内置分类，与后端 KNOWLEDGE_CATEGORIES 一致；接口还会返回用户用过的自定义分类。 */
export const KNOWLEDGE_CATEGORIES = [
  "面经",
  "简历技巧",
  "求职策略",
  "面试问答",
  "公司信息",
  "行业知识",
  "其他",
] as const;
