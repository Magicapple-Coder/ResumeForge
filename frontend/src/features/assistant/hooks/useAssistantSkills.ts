/**
 * 已启用的助手技能。
 *
 * 技能会在服务端改变助手的作答方式，但界面上本来完全看不到这件事——用户只会觉得
 * "今天的助手有点不一样"。把启用中的技能取出来，才能让它可见。
 */

import { useEffect, useState } from "react";
import { listSkills } from "../../../api/skill";
import type { AssistantSkill } from "../../../types";

export function useAssistantSkills() {
  const [skills, setSkills] = useState<AssistantSkill[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    void listSkills()
      .then((items) => {
        if (active) setSkills(items);
      })
      .catch(() => {
        // 取不到技能列表不影响对话本身，静默退回"没有技能"。
      })
      .finally(() => {
        if (active) setLoaded(true);
      });
    return () => {
      active = false;
    };
  }, []);

  return {
    skills,
    enabledSkills: skills.filter((skill) => skill.enabled),
    skillsLoaded: loaded,
  };
}
