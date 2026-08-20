/** 简历微调表单：编辑结构化内容后交由父组件保存并重新渲染。 */
import { DeleteOutlined, PlusOutlined, SaveOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Col,
  Collapse,
  Form,
  Grid,
  Input,
  Modal,
  Row,
  Space,
  Tabs,
  Typography,
} from "antd";
import type { FormListFieldData } from "antd/es/form/FormList";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { ResumeContent } from "../types";

interface Props {
  open: boolean;
  content: ResumeContent | null;
  onClose: () => void;
  onSave: (content: ResumeContent) => Promise<void>;
  title?: string;
  description?: string;
  saveLabel?: string;
  referencePanel?: ReactNode;
  /** 从预览点击进入时使用的结构化字段路径，如 projects.0.description.1。 */
  initialTarget?: string | null;
}

interface ListSectionProps {
  title: string;
  name: string;
  emptyValue: Record<string, string | string[]>;
  children: (field: FormListFieldData) => ReactNode;
}

const splitLines = (value: string): string[] =>
  value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);

const multilineItemProps = {
  getValueProps: (value: string[] | undefined) => ({ value: (value ?? []).join("\n") }),
  normalize: (value: string) => splitLines(value),
};

const TAB_BY_SECTION: Record<string, string> = {
  education: "education",
  experience: "experience",
  campus_experience: "campus",
  projects: "projects",
  skills: "skills",
  awards: "awards",
};

const MULTILINE_FIELDS = new Set([
  "courses",
  "achievements",
  "description",
  "tech_stack",
  "highlights",
]);

function resolveEditorTarget(path: string): { tab: string; name: (string | number)[] } {
  const parts = path
    .split(".")
    .filter(Boolean)
    .map((part) => (/^\d+$/.test(part) ? Number(part) : part));
  const section = typeof parts[0] === "string" ? parts[0] : "";
  const lastPart = parts[parts.length - 1];
  const lastField = parts[parts.length - 2];
  // 预览中的数组要点各有独立路径，但编辑器以一个多行文本框维护整个数组。
  if (
    typeof lastPart === "number" &&
    typeof lastField === "string" &&
    MULTILINE_FIELDS.has(lastField)
  ) {
    parts.pop();
  }
  return { tab: TAB_BY_SECTION[section] ?? "basic", name: parts };
}

function ListSection({ title, name, emptyValue, children }: ListSectionProps) {
  return (
    <Form.List name={name}>
      {(fields, { add, remove }) => (
        <div>
          {fields.map((field, index) => (
            <div
              key={field.key}
              style={{
                position: "relative",
                marginBottom: 12,
                padding: "16px 42px 4px 16px",
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                background: "#fafafa",
              }}
            >
              <div style={{ marginBottom: 10, fontWeight: 600 }}>
                {title} {index + 1}
              </div>
              <Button
                aria-label={`删除${title}`}
                type="text"
                danger
                size="small"
                icon={<DeleteOutlined />}
                style={{ position: "absolute", top: 10, right: 8 }}
                onClick={() => remove(field.name)}
              />
              {children(field)}
            </div>
          ))}
          <Button
            type="dashed"
            block
            icon={<PlusOutlined />}
            onClick={() => add({ ...emptyValue })}
          >
            添加{title}
          </Button>
        </div>
      )}
    </Form.List>
  );
}

function EducationEditor() {
  return (
    <ListSection
      title="教育经历"
      name="education"
      emptyValue={{
        school: "",
        major: "",
        degree: "",
        start_date: "",
        end_date: "",
        gpa: "",
        courses: [],
        achievements: [],
      }}
    >
      {(field) => (
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item
              name={[field.name, "school"]}
              label="学校"
              rules={[{ required: true, message: "请填写学校" }]}
            >
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "major"]} label="专业">
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "degree"]} label="学历">
              <Input />
            </Form.Item>
          </Col>
          <Col xs={12} md={6}>
            <Form.Item name={[field.name, "start_date"]} label="开始时间">
              <Input placeholder="2023.09" />
            </Form.Item>
          </Col>
          <Col xs={12} md={6}>
            <Form.Item name={[field.name, "end_date"]} label="结束时间">
              <Input placeholder="2027.06" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name={[field.name, "gpa"]} label="绩点/排名">
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item {...multilineItemProps} name={[field.name, "courses"]} label="核心课程">
              <Input.TextArea rows={3} placeholder="每行一项" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item {...multilineItemProps} name={[field.name, "achievements"]} label="在校成果">
              <Input.TextArea rows={3} placeholder="每行一项" />
            </Form.Item>
          </Col>
        </Row>
      )}
    </ListSection>
  );
}

function ExperienceEditor() {
  return (
    <ListSection
      title="实习/工作经历"
      name="experience"
      emptyValue={{ company: "", role: "", start_date: "", end_date: "", description: [] }}
    >
      {(field) => (
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item
              name={[field.name, "company"]}
              label="公司"
              rules={[{ required: true, message: "请填写公司" }]}
            >
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "role"]} label="职位">
              <Input />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "start_date"]} label="开始">
              <Input placeholder="2025.03" />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "end_date"]} label="结束">
              <Input placeholder="2025.08" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item {...multilineItemProps} name={[field.name, "description"]} label="工作内容">
              <Input.TextArea rows={5} placeholder="每行一个要点" />
            </Form.Item>
          </Col>
        </Row>
      )}
    </ListSection>
  );
}

function CampusEditor() {
  return (
    <ListSection
      title="校园经历"
      name="campus_experience"
      emptyValue={{ organization: "", role: "", start_date: "", end_date: "", description: [] }}
    >
      {(field) => (
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item
              name={[field.name, "organization"]}
              label="组织/部门"
              rules={[{ required: true, message: "请填写组织/部门" }]}
            >
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "role"]} label="职务/角色">
              <Input />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "start_date"]} label="开始">
              <Input />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "end_date"]} label="结束">
              <Input />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item {...multilineItemProps} name={[field.name, "description"]} label="经历描述">
              <Input.TextArea rows={5} placeholder="每行一个要点" />
            </Form.Item>
          </Col>
        </Row>
      )}
    </ListSection>
  );
}

function ProjectEditor() {
  return (
    <ListSection
      title="项目经历"
      name="projects"
      emptyValue={{
        name: "",
        role: "",
        start_date: "",
        end_date: "",
        tech_stack: [],
        description: [],
        highlights: [],
      }}
    >
      {(field) => (
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item
              name={[field.name, "name"]}
              label="项目名称"
              rules={[{ required: true, message: "请填写项目名称" }]}
            >
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "role"]} label="担任角色">
              <Input />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "start_date"]} label="开始">
              <Input />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "end_date"]} label="结束">
              <Input />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item {...multilineItemProps} name={[field.name, "tech_stack"]} label="技术栈">
              <Input.TextArea rows={2} placeholder="每行一项" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item {...multilineItemProps} name={[field.name, "description"]} label="项目描述">
              <Input.TextArea rows={5} placeholder="每行一个要点" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item {...multilineItemProps} name={[field.name, "highlights"]} label="亮点/成果">
              <Input.TextArea rows={5} placeholder="每行一个要点" />
            </Form.Item>
          </Col>
        </Row>
      )}
    </ListSection>
  );
}

function SkillEditor() {
  return (
    <ListSection title="专业技能" name="skills" emptyValue={{ name: "", level: "" }}>
      {(field) => (
        <Row gutter={12}>
          <Col xs={24} md={12}>
            <Form.Item
              name={[field.name, "name"]}
              label="技能名称"
              rules={[{ required: true, message: "请填写技能名称" }]}
            >
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name={[field.name, "level"]} label="熟练程度">
              <Input placeholder="熟练 / 掌握 / 了解" />
            </Form.Item>
          </Col>
        </Row>
      )}
    </ListSection>
  );
}

function AwardEditor() {
  return (
    <ListSection
      title="荣誉奖项"
      name="awards"
      emptyValue={{ name: "", date: "", description: "" }}
    >
      {(field) => (
        <Row gutter={12}>
          <Col xs={24} md={12}>
            <Form.Item
              name={[field.name, "name"]}
              label="奖项名称"
              rules={[{ required: true, message: "请填写奖项名称" }]}
            >
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name={[field.name, "date"]} label="获奖时间">
              <Input placeholder="2025.10" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name={[field.name, "description"]} label="说明">
              <Input.TextArea rows={3} />
            </Form.Item>
          </Col>
        </Row>
      )}
    </ListSection>
  );
}

export default function ResumeEditorModal({
  open,
  content,
  onClose,
  onSave,
  title = "微调简历内容",
  description,
  saveLabel = "保存并更新预览",
  referencePanel,
  initialTarget,
}: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm<ResumeContent>();
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState("basic");
  const screens = Grid.useBreakpoint();

  useEffect(() => {
    if (!open || !content) return;
    form.setFieldsValue(content);
    const target = initialTarget ? resolveEditorTarget(initialTarget) : null;
    setActiveTab(target?.tab ?? "basic");
    if (!target || target.name.length === 0) return;
    const timer = window.setTimeout(() => {
      form.scrollToField(target.name, { behavior: "smooth", block: "center" });
      const field = form.getFieldInstance(target.name) as { focus?: () => void } | undefined;
      field?.focus?.();
    });
    return () => window.clearTimeout(timer);
  }, [content, form, initialTarget, open]);

  const tabItems = useMemo(
    () => [
      {
        key: "basic",
        label: "基本信息",
        children: (
          <Row gutter={12}>
            <Col xs={24} md={8}>
              <Form.Item name="name" label="姓名">
                <Input />
              </Form.Item>
            </Col>
            <Col xs={12} md={8}>
              <Form.Item name="gender" label="性别">
                <Input />
              </Form.Item>
            </Col>
            <Col xs={12} md={8}>
              <Form.Item name="birth_year" label="出生年份">
                <Input />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="phone" label="手机">
                <Input />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="email" label="邮箱">
                <Input />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="city" label="所在城市">
                <Input />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="job_intent" label="求职意向">
                <Input />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="summary" label="个人总结">
                <Input.TextArea rows={5} />
              </Form.Item>
            </Col>
          </Row>
        ),
      },
      { key: "education", label: "教育", children: <EducationEditor /> },
      { key: "experience", label: "实习/工作", children: <ExperienceEditor /> },
      { key: "campus", label: "校园经历", children: <CampusEditor /> },
      { key: "projects", label: "项目", children: <ProjectEditor /> },
      { key: "skills", label: "技能", children: <SkillEditor /> },
      { key: "awards", label: "荣誉", children: <AwardEditor /> },
    ],
    [],
  );

  const handleFinish = async (values: ResumeContent) => {
    if (!content) return;
    setSaving(true);
    try {
      // 照片不在本次编辑表单中，始终保留已校验的原始值。
      await onSave({ ...content, ...values, photo: content.photo });
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存简历修改失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={title}
      open={open}
      width={referencePanel ? "min(1320px, calc(100vw - 24px))" : "min(1000px, calc(100vw - 24px))"}
      zIndex={1100}
      destroyOnHidden
      maskClosable={!saving}
      onCancel={onClose}
      footer={
        <Space>
          <Button disabled={saving} onClick={onClose}>
            取消
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={() => form.submit()}
          >
            {saveLabel}
          </Button>
        </Space>
      }
      styles={{ body: { maxHeight: "calc(100vh - 180px)", overflowY: "auto" } }}
    >
      <div
        className={`resume-editor-layout${referencePanel ? " resume-editor-layout--with-reference" : ""}`}
      >
        {referencePanel && (
          <div className="resume-editor-reference">
            {screens.lg ? (
              referencePanel
            ) : (
              <Collapse
                size="small"
                items={[
                  {
                    key: "job-reference",
                    label: "查看岗位要求",
                    children: referencePanel,
                  },
                ]}
              />
            )}
          </div>
        )}
        <div className="resume-editor-main">
          {description && (
            <Typography.Text type="secondary" className="resume-editor-description">
              {description}
            </Typography.Text>
          )}
          <Form
            form={form}
            layout="vertical"
            onFinish={(values) => void handleFinish(values as ResumeContent)}
          >
            <Tabs activeKey={activeTab} items={tabItems} onChange={setActiveTab} />
          </Form>
        </div>
      </div>
    </Modal>
  );
}
