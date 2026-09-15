/** 简历编辑器的分区字段表单。 */
import { Col, Form, Input, Row } from "antd";
import ResumeListSection from "./ResumeListSection";
import { multilineItemProps } from "./resumeFieldUtils";

export function EducationEditor() {
  return (
    <ResumeListSection
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
    </ResumeListSection>
  );
}

export function ExperienceEditor() {
  return (
    <ResumeListSection
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
    </ResumeListSection>
  );
}

export function CampusEditor() {
  return (
    <ResumeListSection
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
    </ResumeListSection>
  );
}

export function ProjectEditor() {
  return (
    <ResumeListSection
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
    </ResumeListSection>
  );
}

export function SkillEditor() {
  return (
    <ResumeListSection title="专业技能" name="skills" emptyValue={{ name: "", level: "" }}>
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
    </ResumeListSection>
  );
}

export function AwardEditor() {
  return (
    <ResumeListSection
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
    </ResumeListSection>
  );
}
