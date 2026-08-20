/** 我的资料：基础信息 + 各分区动态列表，整体保存。 */
import {
  CameraOutlined,
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  FileSearchOutlined,
  HolderOutlined,
  SaveOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Form,
  Image,
  Input,
  Modal,
  Row,
  Skeleton,
  Space,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import type { UploadProps } from "antd";
import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { getProfile, parseProfileText, saveProfile } from "../api/profile";
import { AwardSection } from "../components/profile/AwardSection";
import { CampusExperienceSection } from "../components/profile/CampusExperienceSection";
import { EducationSection } from "../components/profile/EducationSection";
import { ExperienceSection } from "../components/profile/ExperienceSection";
import { ProjectSection } from "../components/profile/ProjectSection";
import { SkillSection } from "../components/profile/SkillSection";
import type { Profile } from "../types";
import { mergeParsedProfileValues } from "../utils/profileText";

type ProfileFormValues = Omit<Profile, "id" | "updated_at">;

type ProfileSectionKey =
  | "basic_info"
  | "educations"
  | "experiences"
  | "campus_experiences"
  | "projects"
  | "skills"
  | "awards"
  | "summary";

const DEFAULT_SECTION_ORDER: ProfileSectionKey[] = [
  "basic_info",
  "educations",
  "experiences",
  "campus_experiences",
  "projects",
  "skills",
  "awards",
  "summary",
];
const SECTION_DRAG_THRESHOLD_PX = 6;

const SECTION_LABELS: Record<ProfileSectionKey, string> = {
  basic_info: "基本信息",
  educations: "教育经历",
  experiences: "实习/工作经历",
  campus_experiences: "校园经历",
  projects: "项目经历",
  skills: "专业技能",
  awards: "荣誉奖项",
  summary: "个人总结 / 自我评价",
};

function normalizeSectionOrder(value: string[] | undefined): ProfileSectionKey[] {
  const supported = new Set<ProfileSectionKey>(DEFAULT_SECTION_ORDER);
  const normalized = (value ?? []).filter((key): key is ProfileSectionKey =>
    supported.has(key as ProfileSectionKey),
  );
  return [...normalized, ...DEFAULT_SECTION_ORDER.filter((key) => !normalized.includes(key))];
}

interface SortableProfileSectionProps {
  sectionKey: ProfileSectionKey;
  order: number;
  editable: boolean;
  compact: boolean;
  dragOver: boolean;
  onHandlePointerDown: (
    event: ReactPointerEvent<HTMLButtonElement>,
    sectionKey: ProfileSectionKey,
  ) => void;
  onMoveByOffset: (sectionKey: ProfileSectionKey, offset: -1 | 1) => void;
  children: ReactNode;
}

function SortableProfileSection({
  sectionKey,
  order,
  editable,
  compact,
  dragOver,
  onHandlePointerDown,
  onMoveByOffset,
  children,
}: SortableProfileSectionProps) {
  return (
    <div
      className={`profile-section-sortable${dragOver ? " is-drag-over" : ""}${
        compact ? " is-section-reordering" : ""
      }`}
      style={{ order }}
      data-profile-section-key={sectionKey}
    >
      {editable && (
        <Tooltip title={`拖动或使用上下方向键调整“${SECTION_LABELS[sectionKey]}”顺序`}>
          <button
            type="button"
            className="profile-section-drag-handle"
            aria-label={`拖动调整${SECTION_LABELS[sectionKey]}顺序`}
            onPointerDown={(event) => onHandlePointerDown(event, sectionKey)}
            onKeyDown={(event) => {
              if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
              event.preventDefault();
              onMoveByOffset(sectionKey, event.key === "ArrowUp" ? -1 : 1);
            }}
          >
            <HolderOutlined />
          </button>
        </Tooltip>
      )}
      {compact && (
        <div className="profile-section-compact-label">
          <Typography.Text strong>{SECTION_LABELS[sectionKey]}</Typography.Text>
          <Typography.Text type="secondary">拖到此处</Typography.Text>
        </div>
      )}
      <div className={`profile-section-content${compact ? " is-collapsed" : ""}`}>{children}</div>
    </div>
  );
}

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

export default function ProfilePage() {
  const [form] = Form.useForm<ProfileFormValues>();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [photoReading, setPhotoReading] = useState(false);
  const [sectionOrder, setSectionOrder] = useState<ProfileSectionKey[]>(DEFAULT_SECTION_ORDER);
  const [sectionReorderMode, setSectionReorderMode] = useState(false);
  const [draggingSection, setDraggingSection] = useState<ProfileSectionKey | null>(null);
  const [dragOverSection, setDragOverSection] = useState<ProfileSectionKey | null>(null);
  const [profileTextOpen, setProfileTextOpen] = useState(false);
  const [profileText, setProfileText] = useState("");
  const [profileTextWarnings, setProfileTextWarnings] = useState<string[]>([]);
  const [profileTextParsing, setProfileTextParsing] = useState(false);
  const photoReadId = useRef(0);
  const profileTextRequestId = useRef(0);
  const savedValues = useRef<ProfileFormValues | null>(null);
  const sectionPointerStart = useRef<{ x: number; y: number } | null>(null);
  const sectionDragActivated = useRef(false);
  const photo = Form.useWatch("photo", form) ?? "";

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
  }, [form, message]);

  useEffect(
    () => () => {
      photoReadId.current += 1;
    },
    [],
  );

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
      setSectionOrder(normalizeSectionOrder(nextValues.section_order));
      setSectionReorderMode(false);
      setDraggingSection(null);
      setDragOverSection(null);
      sectionPointerStart.current = null;
      sectionDragActivated.current = false;
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
      setSectionOrder(normalizeSectionOrder(savedValues.current.section_order));
    }
    setSectionReorderMode(false);
    setDraggingSection(null);
    setDragOverSection(null);
    sectionPointerStart.current = null;
    sectionDragActivated.current = false;
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

  const handleSectionPointerDown = (
    event: ReactPointerEvent<HTMLButtonElement>,
    sectionKey: ProfileSectionKey,
  ) => {
    if (!editing || saving || photoReading) return;
    event.preventDefault();
    sectionPointerStart.current = { x: event.clientX, y: event.clientY };
    sectionDragActivated.current = false;
    setSectionReorderMode(true);
    setDraggingSection(sectionKey);
    setDragOverSection(null);
  };

  useEffect(() => {
    if (!draggingSection) return;

    const findSectionAtPoint = (clientX: number, clientY: number): ProfileSectionKey | null => {
      const element = document.elementFromPoint(clientX, clientY);
      const section = element?.closest<HTMLElement>("[data-profile-section-key]");
      const key = section?.dataset.profileSectionKey;
      return key && DEFAULT_SECTION_ORDER.includes(key as ProfileSectionKey)
        ? (key as ProfileSectionKey)
        : null;
    };

    const handlePointerMove = (event: globalThis.PointerEvent) => {
      event.preventDefault();
      const start = sectionPointerStart.current;
      if (!start) return;
      const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
      if (!sectionDragActivated.current && distance < SECTION_DRAG_THRESHOLD_PX) return;
      sectionDragActivated.current = true;
      const target = findSectionAtPoint(event.clientX, event.clientY);
      setDragOverSection(target && target !== draggingSection ? target : null);
    };

    const finishSectionDrag = (event: globalThis.PointerEvent) => {
      event.preventDefault();
      const start = sectionPointerStart.current;
      const distance = start ? Math.hypot(event.clientX - start.x, event.clientY - start.y) : 0;
      const target = findSectionAtPoint(event.clientX, event.clientY);
      if (
        sectionDragActivated.current &&
        distance >= SECTION_DRAG_THRESHOLD_PX &&
        target &&
        target !== draggingSection
      ) {
        setSectionOrder((current) => {
          const next = [...current];
          const sourceIndex = next.indexOf(draggingSection);
          const targetIndex = next.indexOf(target);
          if (sourceIndex < 0 || targetIndex < 0) return current;
          next.splice(sourceIndex, 1);
          next.splice(targetIndex, 0, draggingSection);
          return next;
        });
      }
      sectionPointerStart.current = null;
      sectionDragActivated.current = false;
      setDraggingSection(null);
      setDragOverSection(null);
    };

    document.addEventListener("pointermove", handlePointerMove, { passive: false });
    document.addEventListener("pointerup", finishSectionDrag);
    document.addEventListener("pointercancel", finishSectionDrag);
    return () => {
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", finishSectionDrag);
      document.removeEventListener("pointercancel", finishSectionDrag);
    };
  }, [draggingSection]);

  const toggleSectionReorderMode = () => {
    setSectionReorderMode((current) => {
      if (current) {
        sectionPointerStart.current = null;
        sectionDragActivated.current = false;
        setDraggingSection(null);
        setDragOverSection(null);
      }
      return !current;
    });
  };

  const moveSectionByOffset = (sectionKey: ProfileSectionKey, offset: -1 | 1) => {
    setSectionOrder((current) => {
      const sourceIndex = current.indexOf(sectionKey);
      const targetIndex = sourceIndex + offset;
      if (sourceIndex < 0 || targetIndex < 0 || targetIndex >= current.length) return current;
      const next = [...current];
      next.splice(sourceIndex, 1);
      next.splice(targetIndex, 0, sectionKey);
      return next;
    });
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
      const { warnings } = parsed;
      const currentValues = form.getFieldsValue(true) as Partial<ProfileFormValues>;
      const merged = mergeParsedProfileValues(currentValues as ProfileFormValues, parsed);
      form.setFieldsValue({
        ...merged,
        section_order: sectionOrder,
      });
      setProfileTextWarnings(warnings);
      message.success("已识别并填入资料，请核对后保存");
    } catch (err) {
      if (requestId !== profileTextRequestId.current) return;
      setProfileTextWarnings([]);
      message.error(err instanceof Error ? err.message : "识别个人资料失败");
    } finally {
      if (requestId === profileTextRequestId.current) setProfileTextParsing(false);
    }
  };

  const closeProfileTextModal = () => {
    profileTextRequestId.current += 1;
    setProfileTextParsing(false);
    setProfileTextOpen(false);
  };

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
                onClick={() => {
                  setProfileText("");
                  setProfileTextWarnings([]);
                  setProfileTextOpen(true);
                }}
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
            <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>
              编辑资料
            </Button>
          )}
        </div>
      </div>

      <Form form={form} layout="vertical" disabled={!editing || saving || photoReading}>
        <Form.Item name="photo" hidden>
          <Input />
        </Form.Item>

        <div
          className={`profile-section-stack${sectionReorderMode ? " is-section-reordering" : ""}`}
        >
          <SortableProfileSection
            sectionKey="basic_info"
            order={sectionOrder.indexOf("basic_info")}
            editable={editing}
            compact={sectionReorderMode}
            dragOver={dragOverSection === "basic_info"}
            onHandlePointerDown={handleSectionPointerDown}
            onMoveByOffset={moveSectionByOffset}
          >
            <Row gutter={[16, 16]} align="stretch" style={{ marginBottom: 16 }}>
              <Col xs={{ span: 24, order: 2 }} xl={{ span: 18, order: 1 }}>
                <Card size="small" title="基本信息" className="profile-top-card">
                  <Row gutter={12}>
                    <Col xs={24} sm={12} lg={8}>
                      <Form.Item
                        name="name"
                        label="姓名"
                        rules={[{ required: true, message: "必填" }]}
                      >
                        <Input placeholder="你的姓名" />
                      </Form.Item>
                    </Col>
                    <Col xs={12} sm={6} lg={8}>
                      <Form.Item name="gender" label="性别">
                        <Input placeholder="男 / 女" />
                      </Form.Item>
                    </Col>
                    <Col xs={12} sm={6} lg={8}>
                      <Form.Item name="birth_year" label="出生年份">
                        <Input placeholder="2004" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} lg={8}>
                      <Form.Item name="phone" label="手机号">
                        <Input placeholder="13800000000" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} lg={8}>
                      <Form.Item
                        name="email"
                        label="邮箱"
                        rules={[{ type: "email", message: "邮箱格式不正确" }]}
                      >
                        <Input placeholder="you@example.com" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} lg={8}>
                      <Form.Item name="city" label="所在城市">
                        <Input placeholder="天津" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} lg={8}>
                      <Form.Item name="target_city" label="意向城市">
                        <Input placeholder="北京 / 深圳 / 杭州" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} lg={8}>
                      <Form.Item name="job_intent" label="求职意向">
                        <Input placeholder="如：后端开发工程师" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} lg={8}>
                      <Form.Item name="github" label="GitHub 主页">
                        <Input placeholder="https://github.com/xxx" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} lg={8}>
                      <Form.Item name="personal_website" label="个人网站 / 博客">
                        <Input placeholder="选填" />
                      </Form.Item>
                    </Col>
                  </Row>
                </Card>
              </Col>

              <Col xs={{ span: 24, order: 1 }} xl={{ span: 6, order: 2 }}>
                <Card size="small" title="简历照片" className="profile-top-card">
                  <div className="profile-photo-panel">
                    <div className="profile-photo-frame">
                      {photo ? (
                        <Image src={photo} alt="简历照片" preview={false} />
                      ) : (
                        <UserOutlined className="profile-photo-placeholder" />
                      )}
                    </div>
                    <Space wrap>
                      <Upload
                        accept="image/jpeg,image/png,image/webp"
                        beforeUpload={beforePhotoUpload}
                        showUploadList={false}
                        maxCount={1}
                        disabled={!editing || saving || photoReading}
                      >
                        <Button icon={<CameraOutlined />} loading={photoReading}>
                          {photo ? "更换照片" : "选择照片"}
                        </Button>
                      </Upload>
                      {photo && (
                        <Button
                          danger
                          icon={<DeleteOutlined />}
                          disabled={!editing || saving || photoReading}
                          onClick={() => form.setFieldValue("photo", "")}
                        >
                          移除
                        </Button>
                      )}
                    </Space>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      JPG、PNG 或 WebP，最大 2 MB
                    </Typography.Text>
                  </div>
                </Card>
              </Col>
            </Row>
          </SortableProfileSection>

          <SortableProfileSection
            sectionKey="educations"
            order={sectionOrder.indexOf("educations")}
            editable={editing}
            compact={sectionReorderMode}
            dragOver={dragOverSection === "educations"}
            onHandlePointerDown={handleSectionPointerDown}
            onMoveByOffset={moveSectionByOffset}
          >
            <EducationSection editable={editing} />
          </SortableProfileSection>
          <SortableProfileSection
            sectionKey="experiences"
            order={sectionOrder.indexOf("experiences")}
            editable={editing}
            compact={sectionReorderMode}
            dragOver={dragOverSection === "experiences"}
            onHandlePointerDown={handleSectionPointerDown}
            onMoveByOffset={moveSectionByOffset}
          >
            <ExperienceSection editable={editing} />
          </SortableProfileSection>
          <SortableProfileSection
            sectionKey="campus_experiences"
            order={sectionOrder.indexOf("campus_experiences")}
            editable={editing}
            compact={sectionReorderMode}
            dragOver={dragOverSection === "campus_experiences"}
            onHandlePointerDown={handleSectionPointerDown}
            onMoveByOffset={moveSectionByOffset}
          >
            <CampusExperienceSection editable={editing} />
          </SortableProfileSection>
          <SortableProfileSection
            sectionKey="projects"
            order={sectionOrder.indexOf("projects")}
            editable={editing}
            compact={sectionReorderMode}
            dragOver={dragOverSection === "projects"}
            onHandlePointerDown={handleSectionPointerDown}
            onMoveByOffset={moveSectionByOffset}
          >
            <ProjectSection editable={editing} />
          </SortableProfileSection>
          <SortableProfileSection
            sectionKey="skills"
            order={sectionOrder.indexOf("skills")}
            editable={editing}
            compact={sectionReorderMode}
            dragOver={dragOverSection === "skills"}
            onHandlePointerDown={handleSectionPointerDown}
            onMoveByOffset={moveSectionByOffset}
          >
            <SkillSection editable={editing} />
          </SortableProfileSection>
          <SortableProfileSection
            sectionKey="awards"
            order={sectionOrder.indexOf("awards")}
            editable={editing}
            compact={sectionReorderMode}
            dragOver={dragOverSection === "awards"}
            onHandlePointerDown={handleSectionPointerDown}
            onMoveByOffset={moveSectionByOffset}
          >
            <AwardSection editable={editing} />
          </SortableProfileSection>

          <SortableProfileSection
            sectionKey="summary"
            order={sectionOrder.indexOf("summary")}
            editable={editing}
            compact={sectionReorderMode}
            dragOver={dragOverSection === "summary"}
            onHandlePointerDown={handleSectionPointerDown}
            onMoveByOffset={moveSectionByOffset}
          >
            <Card size="small" title="个人总结 / 自我评价" style={{ marginBottom: 16 }}>
              <Form.Item name="summary" style={{ marginBottom: 0 }}>
                <Input.TextArea
                  rows={4}
                  placeholder="几句话概括你的优势与特点，AI 会结合目标岗位进行润色"
                />
              </Form.Item>
            </Card>
          </SortableProfileSection>
        </div>
      </Form>

      <Modal
        title="粘贴个人资料并识别"
        open={profileTextOpen}
        onCancel={closeProfileTextModal}
        destroyOnHidden
        width={760}
        footer={[
          <Button key="cancel" onClick={closeProfileTextModal} disabled={profileTextParsing}>
            关闭
          </Button>,
          <Button
            key="parse"
            type="primary"
            icon={<FileSearchOutlined />}
            loading={profileTextParsing}
            onClick={() => void parseProfile()}
          >
            识别并填入
          </Button>,
        ]}
        styles={{ body: { paddingRight: 8 } }}
      >
        <Typography.Paragraph type="secondary">
          可粘贴包含基本信息、教育经历、实习/工作经历、校园经历、项目经历、技能和获奖情况的整段文字。识别结果会直接回填当前编辑表单，请核对后再保存。
        </Typography.Paragraph>
        <Input.TextArea
          value={profileText}
          disabled={profileTextParsing}
          onChange={(event) => {
            setProfileText(event.target.value);
            setProfileTextWarnings([]);
          }}
          maxLength={100_000}
          showCount
          placeholder={
            "例如：\n姓名：张三\n教育经历\n天津工业大学｜软件工程｜本科｜2022.09-2026.06\n项目经历\n简历通｜核心开发｜Python、FastAPI"
          }
          autoSize={{ minRows: 14, maxRows: 24 }}
        />
        {profileTextWarnings.length > 0 && (
          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 12 }}
            message={profileTextWarnings.join("；")}
          />
        )}
      </Modal>
    </div>
  );
}
