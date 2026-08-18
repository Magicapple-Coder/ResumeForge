/** 技能标签组：按类别着色展示（岗位卡片与详情共用）。 */
import { Tag } from "antd";
import type { SkillTag } from "../types";

// 类别 -> 标签颜色（antd 内置色板，保持全局一致）
const CATEGORY_COLORS: Record<string, string> = {
  编程语言: "blue",
  前端技术: "cyan",
  后端技术: "geekblue",
  数据库与中间件: "purple",
  人工智能: "magenta",
  云原生与大数据: "green",
  通用能力: "gold",
};

interface Props {
  tags: SkillTag[];
  /** 最多展示数量，超出折叠（默认 5） */
  max?: number;
}

export default function SkillTags({ tags, max = 5 }: Props) {
  if (!tags.length) return null;
  const visible = tags.slice(0, max);
  return (
    <span>
      {visible.map((tag) => (
        <Tag
          key={`${tag.category}-${tag.name}`}
          color={CATEGORY_COLORS[tag.category] ?? "default"}
          style={{ marginBottom: 4 }}
        >
          {tag.name}
        </Tag>
      ))}
      {tags.length > max && <Tag>+{tags.length - max}</Tag>}
    </span>
  );
}
