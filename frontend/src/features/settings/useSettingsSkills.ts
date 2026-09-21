import { App } from "antd";
import { useCallback, useEffect, useState } from "react";
import { deleteSkill, importSkill, listSkills, setSkillEnabled } from "../../api/skill";
import type { AssistantSkill } from "../../types";

/** 设置页「AI 模型」页里技能列表的加载、导入、启停与删除。 */
export function useSettingsSkills() {
  const { message } = App.useApp();
  const [skills, setSkills] = useState<AssistantSkill[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [skillImporting, setSkillImporting] = useState(false);
  const [skillTogglingId, setSkillTogglingId] = useState<number | null>(null);
  const [skillDeletingId, setSkillDeletingId] = useState<number | null>(null);

  const loadSkillList = useCallback(async () => {
    setSkillsLoading(true);
    try {
      setSkills(await listSkills());
    } catch (err) {
      message.error(err instanceof Error ? err.message : "加载技能失败");
    } finally {
      setSkillsLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void loadSkillList();
  }, [loadSkillList]);

  const importSkillFile = async (file: File) => {
    if (skillImporting) return;
    setSkillImporting(true);
    try {
      const saved = await importSkill(file);
      await loadSkillList();
      message.success(`已导入技能「${saved.name}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导入技能失败");
    } finally {
      setSkillImporting(false);
    }
  };

  const toggleSkill = async (skill: AssistantSkill, enabled: boolean) => {
    if (skillTogglingId !== null) return;
    setSkillTogglingId(skill.id);
    try {
      const updated = await setSkillEnabled(skill.id, enabled);
      setSkills((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      message.success(`已${enabled ? "启用" : "停用"}「${skill.name}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "切换技能状态失败");
    } finally {
      setSkillTogglingId(null);
    }
  };

  const removeSkill = async (skill: AssistantSkill) => {
    if (skillDeletingId !== null) return;
    setSkillDeletingId(skill.id);
    try {
      await deleteSkill(skill.id);
      setSkills((current) => current.filter((item) => item.id !== skill.id));
      message.success(`已删除技能「${skill.name}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除技能失败");
    } finally {
      setSkillDeletingId(null);
    }
  };

  return {
    skills,
    skillsLoading,
    skillImporting,
    skillTogglingId,
    skillDeletingId,
    loadSkillList,
    importSkillFile,
    toggleSkill,
    removeSkill,
  };
}
