/** 简历微调表单：编辑结构化内容后交由父组件保存并重新渲染。 */
import { SaveOutlined } from "@ant-design/icons";
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

import {
  EducationEditor,
  ExperienceEditor,
  CampusEditor,
  ProjectEditor,
  SkillEditor,
  AwardEditor,
} from "./resume-editor/ResumeSectionEditors";
import { resolveEditorTarget } from "./resume-editor/ResumeEditorTarget";
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
      keyboard={!saving}
      onCancel={() => {
        if (!saving) onClose();
      }}
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
