/** 资料箱条目类型。 */

/** 资料附件：本机提取出的文字，或一张图片的缩略图。 */
export interface MaterialFile {
  name: string;
  mime_type: string;
  size_bytes: number;
  text: string;
  data_url: string;
}

export interface Material {
  id: number;
  title: string;
  category: string;
  content: string;
  url: string;
  files: MaterialFile[];
  note: string;
  created_at: string;
  updated_at: string;
}

export interface MaterialPayload {
  title: string;
  category: string;
  content: string;
  url: string;
  files: MaterialFile[];
  note: string;
}

/** 内置分类，与后端 MATERIAL_CATEGORIES 一致；接口还会返回用户用过的自定义分类。 */
export const MATERIAL_CATEGORIES = [
  "证书",
  "作品",
  "链接",
  "笔记",
  "实习材料",
  "校园材料",
  "其他",
] as const;
