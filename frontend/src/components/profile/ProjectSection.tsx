/** 项目经历分区。 */
import { Col, Form, Input, Row } from "antd";
import type { FormListFieldData } from "antd/es/form/FormList";
import ProfileSection from "./ProfileSection";
import ReferenceFileField from "./ReferenceFileField";

interface Props {
  editable: boolean;
}

export function ProjectSection({ editable }: Props) {
  return (
    <ProfileSection
      fieldName="projects"
      editable={editable}
      emptyValue={{
        name: "",
        role: "",
        start_date: "",
        end_date: "",
        tech_stack: "",
        description: "",
        highlights: "",
        reference_file_name: "",
        reference_content: "",
      }}
      itemLabel={(item, index) => {
        const name = String(item.name ?? "").trim();
        const role = String(item.role ?? "").trim();
        return [name, role].filter(Boolean).join(" · ") || `项目经历 ${index + 1}`;
      }}
      renderRow={(field: FormListFieldData) => (
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item
              name={[field.name, "name"]}
              label="项目名称"
              rules={[{ required: true, message: "必填" }]}
            >
              <Input placeholder="如：AI 简历生成平台" />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "role"]} label="担任角色">
              <Input placeholder="如：核心开发" />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "start_date"]} label="开始">
              <Input placeholder="2025.01" />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "end_date"]} label="结束">
              <Input placeholder="至今" />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item name={[field.name, "tech_stack"]} label="技术栈">
              <Input placeholder="逗号分隔，如：Python, FastAPI, React" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name={[field.name, "description"]} label="项目描述">
              <Input.TextArea rows={3} placeholder="项目背景、解决了什么问题，每行一条" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name={[field.name, "highlights"]} label="亮点/成果">
              <Input.TextArea rows={3} placeholder="量化成果优先，如：接口性能提升 40%，每行一条" />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <ReferenceFileField listName="projects" fieldName={field.name} editable={editable} />
          </Col>
        </Row>
      )}
    />
  );
}
