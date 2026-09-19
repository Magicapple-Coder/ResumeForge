/** 荣誉奖项分区。 */
import { Col, Form, Input, Row } from "antd";
import type { FormListFieldData } from "antd/es/form/FormList";
import ProfileSection from "./ProfileSection";

interface Props {
  editable: boolean;
}

export function AwardSection({ editable }: Props) {
  return (
    <ProfileSection
      fieldName="awards"
      editable={editable}
      emptyValue={{ name: "", date: "", description: "" }}
      itemLabel={(item, index) => {
        const name = String(item.name ?? "").trim();
        const date = String(item.date ?? "").trim();
        return [name, date].filter(Boolean).join(" · ") || `荣誉奖项 ${index + 1}`;
      }}
      renderRow={(field: FormListFieldData) => (
        <Row gutter={12}>
          <Col xs={24} md={10}>
            <Form.Item
              name={[field.name, "name"]}
              label="奖项名称"
              rules={[{ required: true, message: "必填" }]}
            >
              <Input placeholder="如：全国大学生数学建模竞赛一等奖" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={8} md={6}>
            <Form.Item name={[field.name, "date"]} label="获得时间">
              <Input placeholder="2024.10" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={16} md={8}>
            <Form.Item name={[field.name, "description"]} label="说明">
              <Input placeholder="选填，如：全国前 1%" />
            </Form.Item>
          </Col>
        </Row>
      )}
    />
  );
}
