/** 实习/工作经历分区。 */
import { Col, Form, Input, Row } from "antd";
import type { FormListFieldData } from "antd/es/form/FormList";
import ProfileSection from "./ProfileSection";
import ReferenceFileField from "./ReferenceFileField";

interface Props {
  editable: boolean;
}

export function ExperienceSection({ editable }: Props) {
  return (
    <ProfileSection
      fieldName="experiences"
      editable={editable}
      emptyValue={{
        company: "",
        role: "",
        start_date: "",
        end_date: "",
        description: "",
        reference_file_name: "",
        reference_content: "",
      }}
      itemLabel={(item, index) => {
        const company = String(item.company ?? "").trim();
        const role = String(item.role ?? "").trim();
        return [company, role].filter(Boolean).join(" · ") || `实习/工作经历 ${index + 1}`;
      }}
      renderRow={(field: FormListFieldData) => (
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item
              name={[field.name, "company"]}
              label="公司"
              rules={[{ required: true, message: "必填" }]}
            >
              <Input placeholder="如：字节跳动" />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "role"]} label="职位">
              <Input placeholder="如：后端开发实习生" />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "start_date"]} label="开始">
              <Input placeholder="2025.06" />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "end_date"]} label="结束">
              <Input placeholder="2025.09" />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item name={[field.name, "description"]} label="工作内容">
              <Input.TextArea
                rows={4}
                placeholder="每行一条工作内容，尽量包含做了什么、用了什么技术、结果如何（数字量化更好）"
              />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <ReferenceFileField listName="experiences" fieldName={field.name} editable={editable} />
          </Col>
        </Row>
      )}
    />
  );
}
