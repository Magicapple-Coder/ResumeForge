/** 我的资料页状态、加载保存和拖拽/粘贴操作。 */

import { App, Form, Upload } from "antd";
import type { UploadProps } from "antd";
import { useEffect, useRef, useState } from "react";
import { getProfile, parseProfileText, saveProfile } from "../../api/profile";
import { normalizeSectionOrder } from "../../components/profile/ProfileSectionConfig";
import type { Profile } from "../../types";
import { mergeParsedProfileValues } from "../../utils/profileText";
import { useProfileSectionReorder } from "./useProfileSectionReorder";

export type ProfileFormValues = Omit<Profile, "id" | "updated_at">;

const PHOTO_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const PHOTO_MAX_BYTES = 2 * 1024 * 1024;

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(new Error("读取照片失败"));
    reader.readAsDataURL(file);
  });
}

function toFormValues(profile: Profile): ProfileFormValues {
  return {
    photo: profile.photo,
    name: profile.name,
    gender: profile.gender,
    birth_year: profile.birth_year,
    phone: profile.phone,
    email: profile.email,
    city: profile.city,
    target_city: profile.target_city,
    job_intent: profile.job_intent,
    personal_website: profile.personal_website,
    github: profile.github,
    summary: profile.summary,
    section_order: normalizeSectionOrder(profile.section_order),
    educations: profile.educations,
    experiences: profile.experiences,
    campus_experiences: profile.campus_experiences,
    projects: profile.projects,
    skills: profile.skills,
    awards: profile.awards,
  };
}

export function useProfilePage() {
  const [form] = Form.useForm<ProfileFormValues>();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [photoReading, setPhotoReading] = useState(false);
  const [profileTextOpen, setProfileTextOpen] = useState(false);
  const [profileText, setProfileText] = useState("");
  const [profileTextWarnings, setProfileTextWarnings] = useState<string[]>([]);
  const [profileTextParsing, setProfileTextParsing] = useState(false);
  const photoReadId = useRef(0);
  const profileTextRequestId = useRef(0);
  const savedValues = useRef<ProfileFormValues | null>(null);
  const photo = Form.useWatch("photo", form) ?? "";
  const sectionReorder = useProfileSectionReorder({ editing, saving, photoReading });
  const {
    sectionOrder,
    setSectionOrder,
    sectionReorderMode,
    setSectionReorderMode,
    dragOverSection,
    resetSectionReorder,
    handleSectionPointerDown,
    toggleSectionReorderMode,
    moveSectionByOffset,
  } = sectionReorder;

  useEffect(() => {
    let active = true;
    void getProfile()
      .then((profile) => {
        if (!active) return;
        const values = toFormValues(profile);
        form.setFieldsValue(values);
        setSectionOrder(normalizeSectionOrder(values.section_order));
        savedValues.current = values;
        setSectionReorderMode(false);
      })
      .catch((err) => {
        if (active) message.error(err instanceof Error ? err.message : "加载资料失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [form, message, setSectionOrder, setSectionReorderMode]);

  useEffect(
    () => () => {
      photoReadId.current += 1;
    },
    [],
  );

  const closeProfileTextModal = () => {
    profileTextRequestId.current += 1;
    setProfileTextParsing(false);
    setProfileTextOpen(false);
  };

  const submit = async () => {
    if (!editing || saving || photoReading) return;
    let values: ProfileFormValues;
    try {
      const formValues = await form.validateFields();
      values = { ...formValues, section_order: sectionOrder } as ProfileFormValues;
    } catch {
      return;
    }
    setSaving(true);
    try {
      const profile = await saveProfile(values);
      const nextValues = toFormValues(profile);
      form.setFieldsValue(nextValues);
      savedValues.current = nextValues;
      resetSectionReorder(normalizeSectionOrder(nextValues.section_order));
      setEditing(false);
      message.success("资料已保存，现在可以去岗位广场生成简历了");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const cancelEditing = () => {
    if (saving || photoReading) return;
    if (savedValues.current) {
      form.resetFields();
      form.setFieldsValue(savedValues.current);
      resetSectionReorder(normalizeSectionOrder(savedValues.current.section_order));
    } else {
      resetSectionReorder();
    }
    closeProfileTextModal();
    setEditing(false);
  };

  const beforePhotoUpload: UploadProps["beforeUpload"] = (file) => {
    if (!editing) return Upload.LIST_IGNORE;
    if (!PHOTO_TYPES.has(file.type)) {
      message.error("请选择 JPG、PNG 或 WebP 格式的照片");
      return Upload.LIST_IGNORE;
    }
    if (file.size > PHOTO_MAX_BYTES) {
      message.error("照片不能超过 2 MB");
      return Upload.LIST_IGNORE;
    }
    const readId = ++photoReadId.current;
    setPhotoReading(true);
    void readAsDataUrl(file)
      .then((dataUrl) => {
        if (photoReadId.current === readId) form.setFieldValue("photo", dataUrl);
      })
      .catch((err) => {
        if (photoReadId.current === readId) {
          message.error(err instanceof Error ? err.message : "读取照片失败");
        }
      })
      .finally(() => {
        if (photoReadId.current === readId) setPhotoReading(false);
      });
    return false;
  };

  const parseProfile = async () => {
    const text = profileText.trim();
    if (!text) {
      message.warning("请先粘贴个人资料");
      return;
    }
    setProfileTextParsing(true);
    const requestId = ++profileTextRequestId.current;
    try {
      const parsed = await parseProfileText({ text });
      if (requestId !== profileTextRequestId.current) return;
      const { warnings, recognition_source: recognitionSource } = parsed;
      const currentValues = form.getFieldsValue(true) as Partial<ProfileFormValues>;
      const merged = mergeParsedProfileValues(currentValues as ProfileFormValues, parsed);
      form.setFieldsValue({ ...merged, section_order: sectionOrder });
      setProfileTextWarnings(warnings);
      message.success(
        `${recognitionSource === "ai" ? "已使用 AI" : "已使用本地规则"}识别并填入资料，请核对后保存`,
      );
    } catch (err) {
      if (requestId !== profileTextRequestId.current) return;
      setProfileTextWarnings([]);
      message.error(err instanceof Error ? err.message : "识别个人资料失败");
    } finally {
      if (requestId === profileTextRequestId.current) setProfileTextParsing(false);
    }
  };

  const openProfileTextModal = () => {
    setProfileText("");
    setProfileTextWarnings([]);
    setProfileTextOpen(true);
  };

  const handleProfileTextChange = (value: string) => {
    setProfileText(value);
    setProfileTextWarnings([]);
  };

  return {
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
  };
}
