/** 简历编辑器的可重复分区容器。 */

import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Form } from "antd";
import type { FormListFieldData } from "antd/es/form/FormList";
import type { ReactNode } from "react";

interface Props {
  title: string;
  name: string;
  emptyValue: Record<string, string | string[]>;
  children: (field: FormListFieldData) => ReactNode;
}

export default function ResumeListSection({ title, name, emptyValue, children }: Props) {
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
