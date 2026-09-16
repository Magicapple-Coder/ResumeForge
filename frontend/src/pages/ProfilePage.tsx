/** 我的资料：基础信息 + 各分区动态列表，整体保存。 */
import {
  CloseOutlined,
  EditOutlined,
  FileSearchOutlined,
  HolderOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { Button, Form, Input, Skeleton, Typography } from "antd";
import { useState } from "react";
import GenerateResumeModal from "../components/GenerateResumeModal";
import ManualResumeModal from "../components/ManualResumeModal";
import GeneralResumeSection from "../components/profile/GeneralResumeSection";
import ProfileSectionStack from "../components/profile/ProfileSectionStack";
import ProfileTextModal from "../components/profile/ProfileTextModal";
import { useProfilePage } from "../features/profile/useProfilePage";

export default function ProfilePage() {
  // 通用简历：名称在两个入口之间共享，用户填一次即可。
  const [generalTitle, setGeneralTitle] = useState("");
  const [generateOpen, setGenerateOpen] = useState(false);
  const [writeOpen, setWriteOpen] = useState(false);
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
    images,
    imagesReading,
    addImages,
    removeImage,
    onPasteImages,
    photo,
    submit,
    cancelEditing,
    beforePhotoUpload,
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
              {/* 资料分区很长，通用简历卡片在页面底部；给一个直达入口，
                  否则用户得滚过全部资料才看得到它。 */}
              <Button
                icon={<FileSearchOutlined />}
                onClick={() =>
                  document
                    .getElementById("general-resume-section")
                    ?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
              >
                通用简历
              </Button>
              <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>
                编辑资料
              </Button>
            </>
          )}
        </div>
      </div>

      <Form form={form} layout="vertical" disabled={!editing || saving || photoReading}>
        <Form.Item name="photo" hidden>
          <Input />
        </Form.Item>

        <ProfileSectionStack
          sectionOrder={sectionOrder}
          sectionReorderMode={sectionReorderMode}
          editing={editing}
          saving={saving}
          photoReading={photoReading}
          photo={photo}
          dragOverSection={dragOverSection}
          beforePhotoUpload={beforePhotoUpload}
          onRemovePhoto={() => form.setFieldValue("photo", "")}
          onHandlePointerDown={handleSectionPointerDown}
          onMoveByOffset={moveSectionByOffset}
        />
      </Form>

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
        images={images}
        imagesReading={imagesReading}
        onTextChange={handleProfileTextChange}
        onAddImages={(files) => void addImages(files)}
        onRemoveImage={removeImage}
        onPasteImages={onPasteImages}
        onClose={closeProfileTextModal}
        onParse={() => void parseProfile()}
      />
    </div>
  );
}
