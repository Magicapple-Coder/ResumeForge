/** 个人资料各大分区的排序布局。 */

import { Card, Form, Input } from "antd";
import type { ReactNode } from "react";
import { AwardSection } from "./AwardSection";
import { CampusExperienceSection } from "./CampusExperienceSection";
import { EducationSection } from "./EducationSection";
import { ExperienceSection } from "./ExperienceSection";
import { SortableProfileSection } from "./ProfileSectionShell";
import type { ProfileSectionPointerDownHandler } from "./ProfileSectionShell";
import type { ProfileSectionKey } from "./ProfileSectionConfig";
import ProfileBasicSection from "./ProfileBasicSection";
import { ProjectSection } from "./ProjectSection";
import { SkillSection } from "./SkillSection";

interface Props {
  sectionOrder: ProfileSectionKey[];
  sectionReorderMode: boolean;
  editing: boolean;
  saving: boolean;
  photo: string;
  dragOverSection: ProfileSectionKey | null;
  /** 查看态下被折叠的分区；编辑态忽略（永远展开）。 */
  collapsedSections: Set<ProfileSectionKey>;
  onToggleCollapsed: (sectionKey: ProfileSectionKey) => void;
  onPhotoSelect: (dataUrl: string) => void;
  onHandlePointerDown: ProfileSectionPointerDownHandler;
  onMoveByOffset: (sectionKey: ProfileSectionKey, offset: -1 | 1) => void;
}

export default function ProfileSectionStack({
  sectionOrder,
  sectionReorderMode,
  editing,
  saving,
  photo,
  dragOverSection,
  collapsedSections,
  onToggleCollapsed,
  onPhotoSelect,
  onHandlePointerDown,
  onMoveByOffset,
}: Props) {
  const section = (sectionKey: ProfileSectionKey, children: ReactNode) => (
    <SortableProfileSection
      key={sectionKey}
      sectionKey={sectionKey}
      order={sectionOrder.indexOf(sectionKey)}
      editable={editing}
      compact={sectionReorderMode}
      dragOver={dragOverSection === sectionKey}
      collapsed={!editing && collapsedSections.has(sectionKey)}
      onToggleCollapsed={() => onToggleCollapsed(sectionKey)}
      onHandlePointerDown={onHandlePointerDown}
      onMoveByOffset={onMoveByOffset}
    >
      {children}
    </SortableProfileSection>
  );

  const sectionContent: Record<ProfileSectionKey, ReactNode> = {
    basic_info: (
      <ProfileBasicSection
        photo={photo}
        editing={editing}
        saving={saving}
        onPhotoSelect={onPhotoSelect}
      />
    ),
    educations: <EducationSection editable={editing} />,
    experiences: <ExperienceSection editable={editing} />,
    campus_experiences: <CampusExperienceSection editable={editing} />,
    projects: <ProjectSection editable={editing} />,
    skills: <SkillSection editable={editing} />,
    awards: <AwardSection editable={editing} />,
    summary: (
      <Card size="small" style={{ marginBottom: 16 }}>
        <Form.Item name="summary" style={{ marginBottom: 0 }}>
          <Input.TextArea
            rows={4}
            placeholder="几句话概括你的优势与特点，AI 会结合目标岗位进行润色"
          />
        </Form.Item>
      </Card>
    ),
  };

  return (
    <div className={`profile-section-stack${sectionReorderMode ? " is-section-reordering" : ""}`}>
      {sectionOrder.map((sectionKey) => section(sectionKey, sectionContent[sectionKey]))}
    </div>
  );
}
