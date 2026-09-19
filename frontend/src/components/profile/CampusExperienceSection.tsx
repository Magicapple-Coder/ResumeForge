/** 校园经历分区：学生会、团支部、班级与社团等校内经历。 */
import { Col, Form, Input, Row } from "antd";
import type { FormListFieldData } from "antd/es/form/FormList";
import ProfileSection from "./ProfileSection";
import ReferenceFileField from "./ReferenceFileField";

interface Props {
  editable: boolean;
}

export function CampusExperienceSection({ editable }: Props) {
  return (
    <ProfileSection
      fieldName="campus_experiences"
      editable={editable}
      emptyValue={{
        organization: "",
        role: "",
        start_date: "",
        end_date: "",
        description: "",
        reference_file_name: "",
        reference_content: "",
      }}
      itemLabel={(item, index) => {
        const organization = String(item.organization ?? "").trim();
        const role = String(item.role ?? "").trim();
        return [organization, role].filter(Boolean).join(" · ") || `校园经历 ${index + 1}`;
      }}
      renderRow={(field: FormListFieldData) => (
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "organization"]} label="组织/部门">
              <Input placeholder="如：学生会、团支部、学院社团" />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name={[field.name, "role"]} label="职务/角色">
              <Input placeholder="如：团支书、部长、负责人" />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "start_date"]} label="开始时间">
              <Input placeholder="2023.09" />
            </Form.Item>
          </Col>
          <Col xs={12} md={4}>
            <Form.Item name={[field.name, "end_date"]} label="结束时间">
              <Input placeholder="2024.06 / 至今" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name={[field.name, "description"]} label="经历描述">
              <Input.TextArea rows={3} placeholder="负责的工作、组织的活动与取得的结果，每行一条" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <ReferenceFileField
              listName="campus_experiences"
              fieldName={field.name}
              editable={editable}
            />
          </Col>
        </Row>
      )}
    />
  );
}
