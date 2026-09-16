/**
 * 助手技能状态。
 *
 * 技能会在服务端改变助手的作答方式，但界面上本来完全看不到这件事——用户只会觉得
 * "今天的助手有点不一样"。这里既提供只读的启用列表（页头提示），也提供开关能力
 * （助手页的「技能」下拉可以直接启停，不必跳去设置页）。
 */

import { useCallback, useEffect, useState } from "react";
import { listSkills, setSkillEnabled } from "../../../api/skill";
import type { AssistantSkill } from "../../../types";

export function useAssistantSkills() {
  const [skills, setSkills] = useState<AssistantSkill[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [togglingId, setTogglingId] = useState<number | null>(null);

  const reloadSkills = useCallback(async () => {
    try {
      setSkills(await listSkills());
    } catch {
      // 取不到技能列表不影响对话本身，静默退回"没有技能"。
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void reloadSkills();
  }, [reloadSkills]);

  const toggleSkill = useCallback(async (skill: AssistantSkill, enabled: boolean) => {
    setTogglingId(skill.id);
    try {
      const updated = await setSkillEnabled(skill.id, enabled);
      setSkills((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } finally {
      setTogglingId(null);
    }
  }, []);

  return {
    skills,
    enabledSkills: skills.filter((skill) => skill.enabled),
    skillsLoaded: loaded,
    togglingSkillId: togglingId,
    reloadSkills,
    toggleSkill,
  };
}
