/** 我的资料：基础信息 + 各分区动态列表，整体保存。 */
import {
  CloseOutlined,
  DownOutlined,
  EditOutlined,
  FileSearchOutlined,
  HolderOutlined,
  SaveOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { Button, Form, Input, Skeleton, Typography } from "antd";
import { useState } from "react";
import GenerateResumeModal from "../components/GenerateResumeModal";
import ManualResumeModal from "../components/ManualResumeModal";
import GeneralResumeSection from "../components/profile/GeneralResumeSection";
import { DEFAULT_SECTION_ORDER } from "../components/profile/ProfileSectionConfig";
import type { ProfileSectionKey } from "../components/profile/ProfileSectionConfig";
import ProfileSectionStack from "../components/profile/ProfileSectionStack";
import ProfileTextModal from "../components/profile/ProfileTextModal";
import { useProfilePage } from "../features/profile/useProfilePage";

export default function ProfilePage() {
  // 通用简历：名称在两个入口之间共享，用户填一次即可。
  const [generalTitle, setGeneralTitle] = useState("");
  const [generateOpen, setGenerateOpen] = useState(false);
  const [writeOpen, setWriteOpen] = useState(false);
  // 查看态默认折叠每个分区，只留标题；点标题展开、页头按钮一键全部展开/收起。
  // 编辑态需要看全字段，因此折叠只在非编辑态生效（ProfileSectionStack 里按 `!editing` 取用）。
  const [collapsedSections, setCollapsedSections] = useState<Set<ProfileSectionKey>>(
    () => new Set(DEFAULT_SECTION_ORDER),
  );
  const allExpanded = collapsedSections.size === 0;

  const toggleSection = (sectionKey: ProfileSectionKey) => {
    setCollapsedSections((current) => {
      const next = new Set(current);
      if (next.has(sectionKey)) next.delete(sectionKey);
      else next.add(sectionKey);
      return next;
    });
  };

  const toggleExpandAll = () => {
    setCollapsedSections(allExpanded ? new Set(DEFAULT_SECTION_ORDER) : new Set());
  };
  const {
    form,
    loading,
    saving,
    editing,
    setEditing,
    photoReading,
    sectionOrder,
    sectionReorderMode,
    dragOverSection,
    profileTextOpen,
    profileText,
    profileTextWarnings,
    profileTextParsing,
    profileTextRecognized,
    profileTextSource,
    files,
    filesReading,
    addFiles,
    removeFile,
    onPasteFiles,
    photo,
    submit,
    cancelEditing,
    handleSectionPointerDown,
    toggleSectionReorderMode,
    moveSectionByOffset,
    openProfileTextModal,
    handleProfileTextChange,
    closeProfileTextModal,
    parseProfile,
  } = useProfilePage();

  if (loading) return <Skeleton active paragraph={{ rows: 10 }} />;

  return (
    <div className={`profile-page${editing ? " is-editing" : ""}`}>
      <div className="profile-page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            我的资料
          </Typography.Title>
          <Typography.Text type="secondary">维护生成简历时使用的个人信息与经历</Typography.Text>
        </div>
        <div className="profile-page-header-actions">
          {editing ? (
            <>
              <Button
                icon={<HolderOutlined />}
                disabled={saving || photoReading || profileTextParsing}
                onClick={toggleSectionReorderMode}
              >
                {sectionReorderMode ? "完成模块排序" : "调整模块顺序"}
              </Button>
              <Button
                icon={<FileSearchOutlined />}
                disabled={saving || photoReading || profileTextParsing}
                onClick={openProfileTextModal}
              >
                粘贴文本识别
              </Button>
              <Button
                icon={<CloseOutlined />}
                disabled={saving || photoReading}
                onClick={cancelEditing}
              >
                取消
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                disabled={photoReading}
                onClick={() => void submit()}
              >
                保存全部资料
              </Button>
            </>
          ) : (
            <>
              {/* 资料分区默认折叠，这里给一个一键开关；标签随当前状态翻转。 */}
              <Button
                icon={allExpanded ? <UpOutlined /> : <DownOutlined />}
                onClick={toggleExpandAll}
              >
                {allExpanded ? "全部收起" : "全部展开"}
              </Button>
              <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>
                编辑资料
              </Button>
            </>
          )}
        </div>
      </div>

      {/* 通用简历放在资料分区之前：它不属于资料表单，以前沉在页面最底下，资料一多就得滚到底才看得到。 */}
      <GeneralResumeSection
        onGenerate={(title) => {
          setGeneralTitle(title);
          setGenerateOpen(true);
        }}
        onWrite={(title) => {
          setGeneralTitle(title);
          setWriteOpen(true);
        }}
      />

      <Form form={form} layout="vertical" disabled={!editing || saving || photoReading}>
        <Form.Item name="photo" hidden>
          <Input />
        </Form.Item>

        <ProfileSectionStack
          sectionOrder={sectionOrder}
          sectionReorderMode={sectionReorderMode}
          editing={editing}
          saving={saving}
          photo={photo}
          dragOverSection={dragOverSection}
          collapsedSections={collapsedSections}
          onToggleCollapsed={toggleSection}
          onPhotoSelect={(dataUrl) => form.setFieldValue("photo", dataUrl)}
          onHandlePointerDown={handleSectionPointerDown}
          onMoveByOffset={moveSectionByOffset}
        />
      </Form>

      <GenerateResumeModal
        job={null}
        open={generateOpen}
        initialTitle={generalTitle}
        onClose={() => setGenerateOpen(false)}
      />
      <ManualResumeModal
        job={null}
        open={writeOpen}
        initialTitle={generalTitle}
        onClose={() => setWriteOpen(false)}
      />

      <ProfileTextModal
        open={profileTextOpen}
        text={profileText}
        warnings={profileTextWarnings}
        parsing={profileTextParsing}
        recognizedText={profileTextRecognized}
        recognitionSource={profileTextSource}
        files={files}
        filesReading={filesReading}
        onTextChange={handleProfileTextChange}
        onAddFiles={(incoming) => void addFiles(incoming)}
        onRemoveFile={removeFile}
        onPasteFiles={onPasteFiles}
        onClose={closeProfileTextModal}
        onParse={() => void parseProfile()}
      />
    </div>
  );
}
