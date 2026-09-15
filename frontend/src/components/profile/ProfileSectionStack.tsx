/** 个人资料各大分区的排序布局。 */

import { Card, Form, Input } from "antd";
import type { UploadProps } from "antd";
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
  photoReading: boolean;
  photo: string;
  dragOverSection: ProfileSectionKey | null;
  beforePhotoUpload: UploadProps["beforeUpload"];
  onRemovePhoto: () => void;
  onHandlePointerDown: ProfileSectionPointerDownHandler;
  onMoveByOffset: (sectionKey: ProfileSectionKey, offset: -1 | 1) => void;
}

export default function ProfileSectionStack({
  sectionOrder,
  sectionReorderMode,
  editing,
  saving,
  photoReading,
  photo,
  dragOverSection,
  beforePhotoUpload,
  onRemovePhoto,
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
      onHandlePointerDown={onHandlePointerDown}
      onMoveByOffset={onMoveByOffset}
    >
      {children}
    </SortableProfileSection>
  );

  return (
    <div className={`profile-section-stack${sectionReorderMode ? " is-section-reordering" : ""}`}>
      {section(
        "basic_info",
        <ProfileBasicSection
          photo={photo}
          editing={editing}
          saving={saving}
          photoReading={photoReading}
          beforePhotoUpload={beforePhotoUpload}
          onRemovePhoto={onRemovePhoto}
        />,
      )}
      {section("educations", <EducationSection editable={editing} />)}
      {section("experiences", <ExperienceSection editable={editing} />)}
      {section("campus_experiences", <CampusExperienceSection editable={editing} />)}
      {section("projects", <ProjectSection editable={editing} />)}
      {section("skills", <SkillSection editable={editing} />)}
      {section("awards", <AwardSection editable={editing} />)}
      {section(
        "summary",
        <Card size="small" title="个人总结 / 自我评价" style={{ marginBottom: 16 }}>
          <Form.Item name="summary" style={{ marginBottom: 0 }}>
            <Input.TextArea
              rows={4}
              placeholder="几句话概括你的优势与特点，AI 会结合目标岗位进行润色"
            />
          </Form.Item>
        </Card>,
      )}
    </div>
  );
}
