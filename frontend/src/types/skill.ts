/**
 * 助手技能类型。
 *
 * 名字统一带 `AssistantSkill` 前缀：`Skill`（个人资料技能）和 `ResumeSkill`
 * （简历里的技能）已经占用了短名字，三者含义完全不同，不能混。
 */

/** 一份已导入的技能。提示词正文不回传，列表只需要元信息。 */
export interface AssistantSkill {
  id: number;
  name: string;
  /** 适用场景，来自技能包里的 frontmatter。 */
  description: string;
  enabled: boolean;
  /** 导入时的文件名，用于让用户认出这是哪一版。 */
  source_name: string;
  /** 提示词长度：界面用它提示"这个技能有多大"，但不展示正文。 */
  prompt_chars: number;
  /** 附带的知识文件名清单（正文由助手按需读取）。 */
  files: string[];
  updated_at: string;
}
