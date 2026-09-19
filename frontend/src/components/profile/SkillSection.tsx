/** 专业技能分区。 */
import { Col, Form, Input, Row } from "antd";
import type { FormListFieldData } from "antd/es/form/FormList";
import ProfileSection from "./ProfileSection";

interface Props {
  editable: boolean;
}

export function SkillSection({ editable }: Props) {
  return (
    <ProfileSection
      fieldName="skills"
      editable={editable}
      emptyValue={{ name: "", level: "" }}
      itemLabel={(item, index) => {
        const name = String(item.name ?? "").trim();
        const level = String(item.level ?? "").trim();
        return [name, level].filter(Boolean).join(" · ") || `技能 ${index + 1}`;
      }}
      renderRow={(field: FormListFieldData) => (
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item
              name={[field.name, "name"]}
              label="技能名称"
              rules={[{ required: true, message: "必填" }]}
            >
              <Input placeholder="如：Python / 深度学习 / React" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name={[field.name, "level"]} label="熟练程度">
              <Input placeholder="熟练 / 掌握 / 了解" />
            </Form.Item>
          </Col>
        </Row>
      )}
    />
  );
}
