/**
 * 页头的技能指示。
 *
 * 启用技能会改变助手的作答方式，但回答本身看不出这件事——用户只会觉得"今天它有点不一样"。
 * 把生效中的技能常驻在页头，回答的来由才是可解释的。
 */

import { ExperimentOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import type { AssistantSkill } from "../../../types";
import { summarizeSkillNames } from "../assistantUtils";

export default function AssistantSkillsHint({
  skills,
  onManage,
}: {
  skills: AssistantSkill[];
  onManage: () => void;
}) {
  // 没有启用技能时不占位置：空态里有更合适的引导。
  if (skills.length === 0) return null;
  const names = skills.map((skill) => skill.name).join("、");
  return (
    <Tooltip
      title={
        <>
          回答已按这些技能的要求生成：{names}
          <br />
          点击前往技能工作台管理
        </>
      }
    >
      <Button
        type="text"
        size="small"
        className="assistant-skills-hint"
        icon={<ExperimentOutlined />}
        aria-label={`已启用 ${skills.length} 个助手技能，点击管理`}
        onClick={onManage}
      >
        技能：{summarizeSkillNames(skills)}
      </Button>
    </Tooltip>
  );
}
