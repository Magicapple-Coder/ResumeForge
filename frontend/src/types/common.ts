/** 跨领域共享的基础类型。 */

export interface Page<T> {
  items: T[];
  total: number;
}

export interface SkillTag {
  name: string;
  category: string;
}

/**
 * 一次识别是**谁**认出来的：`ai` 走大模型并逐条校验出处，`local` 走内置规则。
 *
 * 岗位与个人资料的识别接口共用这个字段，界面上也要能一直看到它——两者的可信度不同，
 * 只在识别完成的提示条里出现一次不够。
 */
export type RecognitionSource = "ai" | "local";
